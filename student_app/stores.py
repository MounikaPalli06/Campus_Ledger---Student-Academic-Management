from datetime import date
import re

from werkzeug.security import check_password_hash, generate_password_hash


class DuplicateStudentError(Exception):
    pass


class DuplicateRecordError(Exception):
    pass


class MongoStudentStore:
    def __init__(self, uri, database_name):
        from pymongo import MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        self.collection = self.client[database_name]["students"]
        self.collection.create_index("student_id", unique=True)

    def list_students(self, search=""):
        query = {}
        if search:
            search_pattern = re.escape(search)
            query = {
                "$or": [
                    {"student_id": {"$regex": search_pattern, "$options": "i"}},
                    {"name": {"$regex": search_pattern, "$options": "i"}},
                    {"department": {"$regex": search_pattern, "$options": "i"}},
                ]
            }
        return list(self.collection.find(query, {"_id": 0}).sort("name", 1))

    def get_student(self, student_id):
        return self.collection.find_one({"student_id": student_id}, {"_id": 0})

    def add_student(self, student):
        from pymongo.errors import DuplicateKeyError

        try:
            self.collection.insert_one(student)
        except DuplicateKeyError as error:
            raise DuplicateStudentError from error

    def update_student(self, student_id, student):
        self.collection.update_one({"student_id": student_id}, {"$set": student})

    def close(self):
        self.client.close()


class MongoPerformanceStore:
    def __init__(self, uri, database_name):
        from pymongo import MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        self.collection = self.client[database_name]["academic_records"]
        self.collection.create_index(
            [
                ("student_id", 1),
                ("academic_year", 1),
                ("semester", 1),
                ("exam_date", 1),
                ("subject", 1),
            ],
            unique=True,
        )

    def list_records(self, student_id):
        return list(
            self.collection.find({"student_id": student_id})
        )

    def add_record(self, record):
        from pymongo.errors import DuplicateKeyError

        values = dict(record)
        values["exam_date"] = date.fromisoformat(values["exam_date"]).isoformat()
        identity = {
            key: values[key]
            for key in ("student_id", "academic_year", "semester", "exam_date", "subject")
        }
        try:
            self.collection.update_one(
                identity,
                {"$setOnInsert": values},
                upsert=True,
            )
        except DuplicateKeyError as error:
            raise DuplicateRecordError from error

    def get_record(self, student_id, record_id):
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            object_id = ObjectId(record_id)
        except (InvalidId, TypeError):
            return None
        return self.collection.find_one({"_id": object_id, "student_id": student_id})

    def update_record(self, student_id, record_id, record):
        from bson import ObjectId
        from bson.errors import InvalidId
        from pymongo.errors import DuplicateKeyError

        try:
            object_id = ObjectId(record_id)
        except (InvalidId, TypeError):
            return False
        values = dict(record)
        values["exam_date"] = date.fromisoformat(values["exam_date"]).isoformat()
        values.pop("student_id", None)
        try:
            result = self.collection.update_one(
                {"_id": object_id, "student_id": student_id},
                {"$set": values},
            )
        except DuplicateKeyError as error:
            raise DuplicateRecordError from error
        return result.matched_count == 1

    def close(self):
        self.client.close()


class MongoAccountStore:
    def __init__(self, uri, database_name, admin_username, admin_password):
        from pymongo import MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        self.collection = self.client[database_name]["accounts"]
        self.collection.create_index("username", unique=True)
        self.collection.update_one(
            {"username": admin_username},
            {
                "$setOnInsert": {
                    "username": admin_username,
                    "password_hash": generate_password_hash(admin_password),
                    "role": "admin",
                }
            },
            upsert=True,
        )

    def authenticate(self, username, password):
        account = self.collection.find_one({"username": username})
        if account and check_password_hash(account["password_hash"], password):
            return {
                "username": account["username"],
                "role": account["role"],
                "student_id": account.get("student_id"),
            }
        return None

    def set_student_password(self, student_id, password):
        self.collection.update_one(
            {"username": student_id},
            {
                "$set": {
                    "username": student_id,
                    "student_id": student_id,
                    "password_hash": generate_password_hash(password),
                    "role": "student",
                }
            },
            upsert=True,
        )

    def student_has_account(self, student_id):
        return self.collection.find_one(
            {"username": student_id, "role": "student"}, {"_id": 1}
        ) is not None

    def student_accounts(self, student_ids):
        return {
            account["student_id"]
            for account in self.collection.find(
                {"student_id": {"$in": student_ids}, "role": "student"},
                {"student_id": 1, "_id": 0},
            )
        }

    def change_student_password(self, student_id, current_password, new_password):
        account = self.collection.find_one(
            {"username": student_id, "role": "student"}
        )
        if not account or not check_password_hash(
            account["password_hash"], current_password
        ):
            return False
        self.collection.update_one(
            {"_id": account["_id"]},
            {"$set": {"password_hash": generate_password_hash(new_password)}},
        )
        return True

    def close(self):
        self.client.close()
