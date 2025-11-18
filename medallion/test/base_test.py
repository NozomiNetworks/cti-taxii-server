import base64
import os

from pymongo import MongoClient

from medallion import connect_to_backend, register_blueprints, set_config
from medallion.common import (
    APPLICATION_INSTANCE, get_application_instance_config_values
)
from medallion.middleware.auth import AuthenticationMiddleware


class TaxiiTest():
    type = None
    DATA_FILE = os.path.join(
        os.path.dirname(__file__), "data", "default_data.json",
    )
    TEST_OBJECT = {
        "objects": [
            {
                "type": "course-of-action",
                "spec_version": "2.1",
                "id": "course-of-action--68794cd5-28db-429d-ab1e-1256704ef906",
                "created": "2017-01-27T13:49:53.935Z",
                "modified": "2017-01-27T13:49:53.935Z",
                "name": "Test object"
            }
        ]
    }

    no_config = {}

    config_no_taxii = {
        "backend": {
            "module_class": "MemoryBackend",
            "filename": DATA_FILE,
        },
        "users": {
            "admin": "Password0",
        },
    }

    config_no_auth = {
        "backend": {
            "module_class": "MemoryBackend",
            "filename": DATA_FILE,
        },
        "taxii": {
            "max_page_size": 20,
        },
    }

    config_no_backend = {
        "users": {
            "admin": "Password0",
        },
        "taxii": {
            "max_page_size": 20,
        },
    }

    memory_config = {
        "backend": {
            "module_class": "MemoryBackend",
            "filename": DATA_FILE,
        },
        "users": {
            "admin": "Password0",
        },
        "taxii": {
            "max_page_size": 20,
        },
    }

    mongodb_config = {
        "backend": {
            "module_class": "MongoBackend",
            "uri": "mongodb://root:example@127.0.0.1:27017/",
            "filename": DATA_FILE,
            "clear_db": True
        },
        "users": {},
        "taxii": {
            "max_page_size": 20,
        },
        "auth": {
            "module": "medallion.backends.auth.mongodb_auth",
            "module_class": "AuthMongodbBackend",
            "uri": "mongodb://root:example@localhost:27017/",
            "db_name": "auth"
        }
    }

    def setUp(self, start_threads=True):
        self.__name__ = self.type
        self.app = APPLICATION_INSTANCE
        self.app_context = APPLICATION_INSTANCE.app_context()
        self.app_context.push()
        self.app.testing = True
        if not self.app.blueprints:
            register_blueprints(self.app)
        if self.type == "mongo":
            self.configuration = self.mongodb_config
        elif self.type == "memory":
            self.configuration = self.memory_config
        elif self.type == "memory_no_config":
            self.configuration = self.no_config
        elif self.type == "no_taxii":
            self.configuration = self.config_no_taxii
        elif self.type == "no_auth":
            self.configuration = self.config_no_auth
        elif self.type == "no_backend":
            self.configuration = self.config_no_backend
        else:
            raise RuntimeError("Unknown backend!")
        set_config(self.app, "backend", self.configuration)
        set_config(self.app, "users", self.configuration)
        set_config(self.app, "taxii", self.configuration)
        set_config(self.app, "auth", self.configuration)
        if not start_threads:
            self.app.backend_config["run_cleanup_threads"] = False
        APPLICATION_INSTANCE.medallion_backend = connect_to_backend(get_application_instance_config_values(APPLICATION_INSTANCE,
                                                                                                           "backend"),
                                                                    clear_db=True)
        self.client = APPLICATION_INSTANCE.test_client()
        APPLICATION_INSTANCE.wsgi_app = AuthenticationMiddleware(
            APPLICATION_INSTANCE,
            APPLICATION_INSTANCE.wsgi_app
        )
        if self.type == "memory_no_config" or self.type == "no_auth":
            encoded_auth = "Basic " + base64.b64encode(b"user:pass").decode("ascii")
        elif self.type == "mongo":
            encoded_auth = "Basic " + base64.b64encode(b"root:example").decode("ascii")
            client = MongoClient(self.configuration["backend"]["uri"])
            client.drop_database("auth")
            users = client.auth.create_collection("users")

            users.insert_many([
                {
                    "_id": "admin",
                    "password": "pbkdf2:sha256:150000$vhWiAWXq$a16882c2eaf4dbb5c55566c93ec256c189ebce855b0081f4903f09a23e8b2344"
                },
                {
                    "_id": "user1",
                    "password": "pbkdf2:sha256:150000$TVpGAgEI$dd391524abb0d9107ff5949ef512c150523c388cfa6490d8556d604f90de329e",
                    "license": "nozomi"
                },
                {
                    "_id": "user2",
                    "password": "pbkdf2:sha256:150000$CUo7l9Vz$3ff2da22dcb84c9ba64e2df4d1ee9f7061c1da4f8506618f53457f615178e3f3",
                    "license": "mandiant"
                },
                {
                    "_id": "nozominetworks",
                    "password": "pbkdf2:sha256:1000000$WMhyS14B$67163a08284f6f75eb254a21322425e1f7f91a121357679b0252f076172e43f0"
                }
            ])
        else:
            encoded_auth = "Basic " + base64.b64encode(b"admin:Password0").decode("ascii")
        self.headers = {"Accept": "application/taxii+json;version=2.1", "Authorization": encoded_auth}
        self.post_headers = {
            "Content-Type": "application/taxii+json;version=2.1",
            "Accept": "application/taxii+json;version=2.1",
            "Authorization": encoded_auth
        }
        self.nozomi_auth_headers = {
            'Accept': "application/taxii+json;version=2.1",
            'Authorization': 'Basic bm96b21pbmV0d29ya3M6dGVzdA=='  # nozominetworks:test
        }
        self.post_nozomi_auth_headers = {
            "Content-Type": "application/taxii+json;version=2.1",
            "Accept": "application/taxii+json;version=2.1",
            'Authorization': 'Basic bm96b21pbmV0d29ya3M6dGVzdA=='  # nozominetworks:test
        }
        self.test_user_nozomi_license_headers = {
            "Content-Type": "application/taxii+json;version=2.1",
            "Accept": "application/taxii+json;version=2.1",
            'Authorization': 'Basic dXNlcjE6UGFzc3dvcmQx'  # user1:Password1
        }
        self.test_user_mandiant_license_headers = {
            "Content-Type": "application/taxii+json;version=2.1",
            "Accept": "application/taxii+json;version=2.1",
            'Authorization': 'Basic dXNlcjI6UGFzc3dvcmQy'  # user2:Password2
        }

    def tearDown(self):
        self.app_context.pop()
