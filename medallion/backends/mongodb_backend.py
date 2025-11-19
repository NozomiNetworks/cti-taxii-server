from copy import deepcopy
import datetime
import io
import json
import logging
import uuid

import environ
from pymongo import ASCENDING, IndexModel, MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.synchronous.collection import Collection
from six import string_types

from ..common import (
    APPLICATION_INSTANCE, create_resource, datetime_to_float,
    datetime_to_string, datetime_to_string_stix, determine_spec_version,
    determine_version, float_to_datetime, generate_status,
    generate_status_details, get_application_instance_config_values,
    get_custom_headers, string_to_datetime
)
from ..exceptions import (
    InitializationError, MongoBackendError, ProcessingError
)
from ..filters.mongodb_next_gen_filter import MongoDBNextGenFilter
from .base import Backend

# Module-level logger
log = logging.getLogger(__name__)


def catch_mongodb_error(func):
    """Catch mongodb availability error"""

    def api_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            raise MongoBackendError("Unable to connect to MongoDB", 500, e)

    return api_wrapper


def find_manifest_entries_for_id(obj, manifest):
    for m in manifest:
        if m["id"] == obj["id"]:
            if "modified" in obj:
                if m["version"] == obj["modified"]:
                    return m
            else:
                # handle data markings
                if m["version"] == obj["created"]:
                    return m


class MongoBackend(Backend):
    # access control is handled at the views level

    @environ.config(prefix="MONGO")
    class Config(object):
        uri = environ.var()

    def __init__(self, **kwargs):
        try:
            self.client = MongoClient(kwargs.get("uri"))

            # unless clearing the db has been explicitly specified, don't initialize if the discovery_database exits
            # the discovery_databases is a minimally viable database,
            if not self.database_established() or kwargs.get("clear_db"):
                self.clear_db()
                if kwargs.get("filename"):
                    log.info("Initializing Mongo DB backend using " + kwargs.get("filename"))
                    self.initialize_mongodb_with_data(kwargs.get("filename"))
                    self.object_manifest_check()

            super(MongoBackend, self).__init__(**kwargs)

        except ConnectionFailure:
            log.error("Unable to establish a connection to MongoDB server {}".format(kwargs.get("uri")))

    def database_established(self):
        """
        Checks to see if a medallion database exists
        """
        return "discovery_database" in self.client.list_database_names()

    def _get_next_doc_id(self, pagination_collection: Collection, next_id: tuple[str, str] | None, args: dict) -> str | None:
        """Get the pagination token given the current request's next field and filters.

        If filters change and a next field that does not match any stored pagination token, it will raise a ProcessingError exception.

        The next field is composed by the date_added and id of the last document seen in the previous request.
        The date_added is used to filter the document using MongoDB filter.
        The version is used to manually filter the documents with the same date_added value.
        """
        if not next_id:
            return None

        if doc := pagination_collection.find_one(args):
            return doc["last_doc_last_seen"]

        raise ProcessingError("The server did not understand the request or filter parameters: 'next' not valid", 400)

    def _create_next(self, pagination_collection: Collection, next_id: tuple[str, str] | None, args: dict) -> str | None:
        """Create a next pagination token for the current request, based on the actual filters.

        The next field of the original request is changed with the new one.
        """
        if not next_id:
            return None

        new_uuid = str(uuid.uuid4())
        new_args = deepcopy(args)
        new_args['next'] = new_uuid
        pagination_collection.insert_one(
            {
                "last_doc_last_seen": next_id,
                "creation_time": datetime.datetime.now(datetime.UTC),
                **new_args
            }
        )
        return new_uuid

    def _validate_object_id(self, manifest_info, collection_id, object_id):
        result = list(manifest_info.find({"_collection_id": collection_id, "id": object_id}).limit(1))
        if len(result) == 0:
            raise ProcessingError("Object '{}' not found".format(object_id), 404)

    def _pop_expired_sessions(self):
        # next id deletion will be managed by TTL
        pass

    def _pop_old_statuses(self):
        if "discovery_database" in self.client.list_database_names():
            api_roots = self._get_all_api_roots()
            if api_roots:
                status_retention_in_milliseconds = self.status_retention * 1000
                for ar in api_roots:
                    statuses_of_api_root = self._get_api_root_statuses(ar)
                    result = statuses_of_api_root.aggregate([
                            {
                                "$project": {
                                    "id": 1,
                                    "date_difference": {
                                        "$subtract": [
                                            "$$NOW",
                                            {
                                                "$dateFromString": {
                                                    "dateString": "$request_timestamp"
                                                }
                                            }
                                        ]
                                    },
                                }
                            },
                            {
                                "$match": {
                                    "date_difference": {
                                        "$gt": status_retention_in_milliseconds
                                    }
                                }
                            }
                        ]
                    )
                    for doc in result:
                        log.info("Status {} was deleted from {} because it was older than the status retention time".format(doc["id"], ar))
                        statuses_of_api_root.delete_one({"_id": doc["_id"]})

    @staticmethod
    def _get_object_manifest(objects_found, more, next_id):
        for obj in objects_found:
            obj["date_added"] = datetime_to_string(float_to_datetime(obj["date_added"]))
            obj["version"] = datetime_to_string_stix(float_to_datetime(obj["version"]))

        manifest_resource = create_resource("objects", objects_found, more, next_id)
        return manifest_resource

    def object_manifest_check(self):
        """
        Checks for manifests in each object, throws an error if not present.
        """
        db = self.client
        objects_exists = False
        for api_root in db.list_database_names():
            cols = db[api_root].list_collection_names()
            if "objects" not in cols:
                continue
            objects_exists = True
            api_root_db = db[api_root]
            objects = api_root_db["objects"]
            for result in objects.find({}):
                if "_manifest" not in result:
                    field_to_use = 'created'
                    if "modified" in result:
                        field_to_use = 'modified'
                    raise InitializationError("Object {} from {} is missing a manifest".format(result['id'], result[field_to_use]), 408)
                if not result['_manifest']:
                    field_to_use = 'created'
                    if "modified" in result:
                        field_to_use = 'modified'
                    raise InitializationError("Object {} from {} has a null manifest".format(result['id'], result[field_to_use]), 408)
        if not objects_exists:
            raise InitializationError("Could not find any objects in database", 408)

    @catch_mongodb_error
    def _update_manifest(self, api_root, collection_id, media_type):
        api_root_db = self.client[api_root]
        collection_info = api_root_db["collections"]

        # update media_types in collection if a new one is present.
        info = collection_info.find_one({"id": collection_id})
        if media_type not in info["media_types"]:
            info["media_types"].append(media_type)
            collection_info.update_one(
                {"id": collection_id},
                {"$set": {"media_types": info["media_types"]}}
            )

    @catch_mongodb_error
    def server_discovery(self):
        discovery_db = self.client["discovery_database"]
        discovery_info = discovery_db["discovery_information"]
        info = discovery_info.find_one()
        if info:
            info.pop("_id")
        return info

    @catch_mongodb_error
    def get_collections(self, api_root):
        if api_root not in self.client.list_database_names():
            return None  # must return None, so 404 is raised

        api_root_db = self.client[api_root]
        collection_info = api_root_db["collections"]
        collections = list(collection_info.find({}, {"_id": 0}))
        # interop wants results sorted by id - no need to check for interop option
        if get_application_instance_config_values(APPLICATION_INSTANCE, "taxii", "interop_requirements"):
            collections = sorted(collections, key=lambda o: o["id"])
        return create_resource("collections", collections)

    @catch_mongodb_error
    def get_collection(self, api_root, collection_id):
        if api_root not in self.client.list_database_names():
            return None  # must return None, so 404 is raised

        api_root_db = self.client[api_root]
        collection_info = api_root_db["collections"]
        info = collection_info.find_one({"id": collection_id}, {"_id": 0, "license": 0})
        return info

    def get_collection_license(self, api_root: str, collection_id: str) -> str | None:
        if api_root not in self.client.list_database_names():
            return None  # must return None, so 404 is raised

        api_root_db = self.client[api_root]
        collection_info = api_root_db["collections"]
        if (info := collection_info.find_one({"id": collection_id})) is None:
            return None

        return info["license"]

    @catch_mongodb_error
    def get_object_manifest(self, api_root, collection_id, filter_args, allowed_filters, limit):
        api_root_db = self.client[api_root]
        _next = self._get_next_doc_id(api_root_db["pagination"], filter_args.get("next"), filter_args)
        full_filter_next_gen = MongoDBNextGenFilter(
            filter_args,
            {"_collection_id": {"$eq": collection_id}},
            allowed_filters,
            api_root_db,
            {"next": _next, "limit": limit}
        )

        results, _next = full_filter_next_gen.process_objects_next_gen_filter(allowed_filters)

        next_id, more = _next, _next is not None
        manifests = [obj["_manifest"] for obj in results]
        next_id = self._create_next(api_root_db["pagination"], next_id, filter_args)

        manifest_resource = self._get_object_manifest(manifests, more, next_id)
        headers = get_custom_headers(manifest_resource)

        return create_resource("objects", manifest_resource["objects"], more, next_id), headers

    @catch_mongodb_error
    def get_api_root_information(self, api_root_name):
        db = self.client["discovery_database"]
        api_root_info = db["api_root_info"]
        info = api_root_info.find_one(
            {"_name": api_root_name},
            {"_id": 0, "_url": 0, "_name": 0}
        )
        return info

    @catch_mongodb_error
    def _get_api_root_statuses(self, api_root):
        api_root_db = self.client[api_root]
        return api_root_db["status"]

    @catch_mongodb_error
    def get_status(self, api_root, status_id):
        api_root_db = self.client[api_root]
        status_info = api_root_db["status"]
        result = status_info.find_one(
            {"id": status_id},
            {"_id": 0}
        )
        return result

    @catch_mongodb_error
    def get_objects(self, api_root, collection_id, filter_args, allowed_filters, limit):
        api_root_db = self.client[api_root]
        _next = self._get_next_doc_id(api_root_db["pagination"], filter_args.get("next"), filter_args)

        full_filter_next_gen = MongoDBNextGenFilter(
            filter_args,
            {"_collection_id": {"$eq": collection_id}},
            allowed_filters,
            api_root_db,
            {"next": _next, "limit": limit}
        )

        # Note: error handling was not added to following call as mongo will
        # handle (user supplied) filters gracefully if they don't exist
        objects_found, _next = full_filter_next_gen.process_objects_next_gen_filter(allowed_filters)

        for obj in objects_found:
            if "modified" in obj:
                obj["modified"] = datetime_to_string_stix(float_to_datetime(obj["modified"]))
            if "created" in obj:
                obj["created"] = datetime_to_string_stix(float_to_datetime(obj["created"]))

        next_id, more = _next, _next is not None
        next_id = self._create_next(api_root_db["pagination"], next_id, filter_args)

        manifests = [obj["_manifest"] for obj in objects_found]
        manifest_resource = self._get_object_manifest(manifests, more, next_id)
        headers = get_custom_headers(manifest_resource)

        return create_resource("objects", objects_found, more, next_id), headers

    @catch_mongodb_error
    def _add_status(self, api_root_name, status):
        api_root_db = self.client[api_root_name]
        api_root_db["status"].insert_one(status)

    @catch_mongodb_error
    def add_objects(self, api_root, collection_id, objs, request_time):
        api_root_db = self.client[api_root]
        objects_info = api_root_db["objects"]
        objects_cache_info = api_root_db["objects_version_cache"]
        failed = 0
        succeeded = 0
        pending = 0
        successes = []
        failures = []
        media_fmt = "application/stix+json;version={}"

        try:
            for new_obj in objs["objects"]:
                media_type = media_fmt.format(determine_spec_version(new_obj))
                mongo_query = {"_collection_id": collection_id, "id": new_obj["id"], "_manifest.media_type": media_type}
                if "modified" in new_obj:
                    mongo_query["_manifest.version"] = datetime_to_float(string_to_datetime(new_obj["modified"]))
                existing_entry = objects_info.find_one(mongo_query)
                obj_version = determine_version(new_obj, request_time)
                obj_version_float = datetime_to_float(string_to_datetime(obj_version))

                if existing_entry:
                    message = "Object already added"

                else:
                    message = None
                    new_obj.update({"_collection_id": collection_id})
                    if "modified" in new_obj:
                        new_obj["modified"] = datetime_to_float(string_to_datetime(new_obj["modified"]))
                    if "created" in new_obj:
                        new_obj["created"] = datetime_to_float(string_to_datetime(new_obj["created"]))
                    _manifest = {
                        "id": new_obj["id"],
                        "date_added": datetime_to_float(request_time),
                        "version": obj_version_float,
                        "media_type": media_type,
                    }
                    new_obj.update({"_manifest": _manifest})
                    objects_info.insert_one(new_obj)

                    self.add_object_in_cache(objects_cache_info, new_obj, obj_version_float)

                # else: we already have the object, so this is a
                # no-op.

                status_detail = generate_status_details(
                    new_obj["id"], obj_version, message
                )
                successes.append(status_detail)
                succeeded += 1
        except Exception as e:
            # log.exception(e)
            raise ProcessingError("While processing supplied content, an error occurred", 422, e)

        status = generate_status(
            datetime_to_string(request_time), "complete", succeeded, failed,
            pending, successes=successes, failures=failures,
        )
        api_root_db["status"].insert_one(status)
        status.pop("_id", None)
        return status

    @catch_mongodb_error
    def get_object(self, api_root, collection_id, object_id, filter_args, allowed_filters, limit):
        api_root_db = self.client[api_root]
        objects_info = api_root_db["objects"]
        # set manually to properly retrieve manifests, and early to not break the pagination checks
        filter_args["match[id]"] = object_id

        self._validate_object_id(objects_info, collection_id, object_id)
        _next = self._get_next_doc_id(api_root_db["pagination"], filter_args.get("next"), filter_args)

        full_filter_next_gen = MongoDBNextGenFilter(
            filter_args,
            {"_collection_id": {"$eq": collection_id}, "id": {"$eq": object_id}},
            allowed_filters,
            api_root_db,
            {"next": _next, "limit": limit}
        )

        # Note: error handling was not added to following call as mongo will
        # handle (user supplied) filters gracefully if they don't exist
        objects_found, _next = full_filter_next_gen.process_objects_next_gen_filter(allowed_filters)

        for obj in objects_found:
            if "modified" in obj:
                obj["modified"] = datetime_to_string_stix(float_to_datetime(obj["modified"]))
            if "created" in obj:
                obj["created"] = datetime_to_string_stix(float_to_datetime(obj["created"]))

        next_id, more = _next, _next is not None
        next_id = self._create_next(api_root_db["pagination"], next_id, filter_args)
        manifests = [obj["_manifest"] for obj in objects_found]
        manifest_resource = self._get_object_manifest(manifests, more, next_id)
        headers = get_custom_headers(manifest_resource)

        return create_resource("objects", objects_found, more, next_id), headers

    @catch_mongodb_error
    def delete_object(self, api_root, collection_id, object_id, filter_args, allowed_filters):
        api_root_db = self.client[api_root]
        objects_info = api_root_db["objects"]
        objects_cache_info = api_root_db["objects_version_cache"]

        full_filter_next_gen = MongoDBNextGenFilter(
            filter_args,
            {"_collection_id": {"$eq": collection_id}, "id": {"$eq": object_id}},
            allowed_filters,
            api_root_db,
            {}
        )

        # Note: error handling was not added to following call as mongo will
        # handle (user supplied) filters gracefully if they don't exist
        objects_found, _ = full_filter_next_gen.process_objects_next_gen_filter(allowed_filters)
        if objects_found:
            for obj in objects_found:
                obj_version = obj["_manifest"]["version"]
                objects_info.delete_one(
                    {"_collection_id": collection_id, "id": object_id, "_manifest.version": obj_version}
                )

            # Recreate the object cache with all the objects still present
            objects_cache_info.delete_one({"collection_id": collection_id, "id": object_id})
            for obj in api_root_db.objects.find({"_collection_id": collection_id, "id": object_id}):
                obj["_collection_id"] = collection_id
                self.add_object_in_cache(objects_cache_info, obj, obj["_manifest"]["version"])

        else:
            raise ProcessingError("Object '{}' not found".format(object_id), 404)

    @catch_mongodb_error
    def get_object_versions(self, api_root, collection_id, object_id, filter_args, allowed_filters, limit):
        api_root_db = self.client[api_root]
        objects_info = api_root_db["objects"]
        # set manually to properly retrieve manifests, and early to not break the pagination checks
        filter_args["match[id]"] = object_id
        filter_args["match[version]"] = "all"

        self._validate_object_id(objects_info, collection_id, object_id)
        _next = self._get_next_doc_id(api_root_db["pagination"], filter_args.get("next"), filter_args)

        full_filter_next_gen = MongoDBNextGenFilter(
            filter_args,
            {"_collection_id": {"$eq": collection_id}, "id": {"$eq": object_id}},
            allowed_filters,
            api_root_db,
            {"next": _next, "limit": limit}
        )

        manifests_found, _next = full_filter_next_gen.process_manifests_next_gen_filter(allowed_filters)
        versions = list(map(lambda x: datetime_to_string_stix(float_to_datetime(x["version"])), manifests_found))

        next_id, more = _next, _next is not None
        next_id = self._create_next(api_root_db["pagination"], next_id, filter_args)
        manifest_resource = self._get_object_manifest(manifests_found, more, next_id)
        headers = get_custom_headers(manifest_resource)

        return create_resource("versions", versions, more, next_id), headers

    def load_data_from_file(self, filename):
        try:
            if isinstance(filename, string_types):
                with io.open(filename, "r", encoding="utf-8") as infile:
                    self.json_data = json.load(infile)
            else:
                self.json_data = json.load(filename)
        except Exception as e:
            raise InitializationError("Problem loading initialization data from {0}".format(filename), 408, e)

    def initialize_mongodb_with_data(self, filename):
        self.load_data_from_file(filename)
        if "/discovery" in self.json_data:
            db = self.client["discovery_database"]
            db["discovery_information"].insert_one(self.json_data["/discovery"])
        else:
            raise InitializationError("No discovery information provided when initializing the Mongo DB")
        api_root_info_db = db["api_root_info"]
        for api_root_name, api_root_data in self.json_data.items():
            if api_root_name == "/discovery":
                continue
            url = list(filter(lambda a: api_root_name in a, self.json_data["/discovery"]["api_roots"]))[0]
            api_root_data["information"]["_url"] = url
            api_root_data["information"]["_name"] = api_root_name
            api_root_info_db.insert_one(api_root_data["information"])
            self.client.drop_database(api_root_name)
            api_db = self.client[api_root_name]
            if api_root_data["status"]:
                api_db["status"].insert_many(api_root_data["status"])
            else:
                api_db.create_collection("status")
            api_db.create_collection("collections")
            api_db.create_collection("objects")

            # Cache objects version to keep track of the latest object's version
            api_db.create_collection("objects_version_cache")
            api_db.create_collection("pagination")

            for collection in api_root_data["collections"]:
                collection_id = collection["id"]
                objects = collection["objects"]
                manifest = collection["manifest"]
                # these are not in the collections mongodb collection (both TAXII and Mongo DB use the term collection)
                collection.pop("objects")
                collection.pop("manifest")
                api_db["collections"].insert_one(collection)
                for obj in objects:
                    obj["_collection_id"] = collection_id
                    obj["_manifest"] = find_manifest_entries_for_id(obj, manifest)
                    obj_version_float = datetime_to_float(string_to_datetime(obj["_manifest"]["version"]))
                    obj["_manifest"]["date_added"] = datetime_to_float(string_to_datetime(obj["_manifest"]["date_added"]))
                    obj["_manifest"]["version"] = obj_version_float
                    obj["created"] = datetime_to_float(string_to_datetime(obj["created"]))
                    if "modified" in obj:
                        # not for data markings
                        obj["modified"] = datetime_to_float(string_to_datetime(obj["modified"]))
                    api_db["objects"].insert_one(obj)

                    self.add_object_in_cache(api_db["objects_version_cache"], obj, obj_version_float)

                id_index = IndexModel([("id", ASCENDING)])
                type_index = IndexModel([("type", ASCENDING)])
                collection_index = IndexModel([("_collection_id", ASCENDING)])
                date_index = IndexModel([("_manifest.date_added", ASCENDING)])
                version_index = IndexModel([("_manifest.version", ASCENDING)])
                date_and_spec_index = IndexModel([("_manifest.media_type", ASCENDING), ("_manifest.date_added", ASCENDING)])
                version_and_spec_index = IndexModel([("_manifest.media_type", ASCENDING), ("_manifest.version", ASCENDING)])
                collection_and_date_index = IndexModel([("_collection_id", ASCENDING), ("_manifest.date_added", ASCENDING)])
                api_db["objects"].create_indexes(
                    [id_index, type_index, date_index, version_index, collection_index, date_and_spec_index,
                     version_and_spec_index, collection_and_date_index]
                )

    @staticmethod
    def add_object_in_cache(object_cache_coll: Collection, obj: dict, obj_version_float: float):
        if "2.0" in obj["_manifest"]["media_type"]:
            target_latest_field = "latest_version_2_0"
            target_earliest_field = "earliest_version_2_0"
        else:
            target_latest_field = "latest_version_2_1"
            target_earliest_field = "earliest_version_2_1"

        # upsert the first version in the cache
        object_cache_coll.update_one(
            filter={"id": obj["id"], "collection_id": obj["_collection_id"]},
            update={
                "$max": {
                    target_latest_field: float(obj_version_float),
                    "last_spec": obj["_manifest"]["media_type"]
                },
                "$min": {
                    target_earliest_field: float(obj_version_float)
                }
            },
            upsert=True
        )

    def clear_db(self):
        if "discovery_database" in self.client.list_database_names():
            log.info("Clearing database")
            self.client.drop_database("discovery_database")
        discovery_db = self.client["discovery_database"]
        api_root_info = discovery_db["api_root_info"]
        for api_info in api_root_info.find({}):
            self.client.drop_database(api_info["_name"])
        self.client.drop_database("discovery_database")
        # db with empty tables
        log.info("Creating empty database")
        discovery_db = self.client.get_database("discovery_database")
        discovery_db.create_collection("discovery_information")
        discovery_db.create_collection("api_root_info")
        return discovery_db
