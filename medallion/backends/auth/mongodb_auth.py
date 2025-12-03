import logging

from .base import AuthBackend

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
except ImportError:
    raise ImportError("'pymongo' package is required to use this module.")

# Module-level logger
log = logging.getLogger(__name__)


class AuthMongodbBackend(AuthBackend):
    def __init__(self, uri, **kwargs):
        try:
            self.client = MongoClient(uri)
            self.db_name = kwargs["db_name"]
            # The ismaster command is cheap and does not require auth.
            # self.client.admin.command("ismaster")
        except ConnectionFailure:
            log.error("Unable to establish a connection to MongoDB server {}".format(uri))

    def get_password_hash(self, username):
        db = self.client[self.db_name]
        users = db['users']
        if user_obj := users.find_one({"_id": username}):
            return user_obj['password']
        else:
            return None

    def get_user_by_username(self, username: str) -> dict | None:
        db = self.client[self.db_name]
        users = db['users']
        return users.find_one({"_id": username})

    def get_all_users(self) -> list[dict]:
        db = self.client[self.db_name]
        users = db['users']
        return list(users.find({}))

    def add_user(self, user_info: dict):
        db = self.client[self.db_name]
        users = db['users']
        users.insert_one(user_info)
