import unittest

from flask import Flask

from student_app import create_app, initialize_store


class FakeStudentStore:
    def __init__(self):
        self.students = {}

    def list_students(self, search=""):
        values = list(self.students.values())
        if search:
            values = [student for student in values if search.lower() in str(student).lower()]
        return values

    def get_student(self, student_id):
        return self.students.get(student_id)

    def add_student(self, student):
        self.students[student["student_id"]] = student

    def update_student(self, student_id, student):
        self.students[student_id].update(student)


class FakePerformanceStore:
    def __init__(self):
        self.records = []
        self.next_id = 1

    def list_records(self, student_id):
        return [record for record in self.records if record["student_id"] == student_id]

    def add_record(self, record):
        saved = dict(record)
        saved["_id"] = str(self.next_id)
        self.next_id += 1
        self.records.append(saved)

    def get_record(self, student_id, record_id):
        return next(
            (
                record for record in self.records
                if record["student_id"] == student_id and record["_id"] == record_id
            ),
            None,
        )

    def update_record(self, student_id, record_id, record):
        existing = self.get_record(student_id, record_id)
        if not existing:
            return False
        existing.update(record)
        return True


class FakeAccountStore:
    def __init__(self):
        self.accounts = {"admin": {"username": "admin", "password": "admin-secret", "role": "admin"}}

    def authenticate(self, username, password):
        account = self.accounts.get(username)
        if not account or account["password"] != password:
            return None
        return {key: value for key, value in account.items() if key != "password"}

    def set_student_password(self, student_id, password):
        self.accounts[student_id] = {
            "username": student_id,
            "student_id": student_id,
            "password": password,
            "role": "student",
        }

    def student_has_account(self, student_id):
        return student_id in self.accounts

    def student_accounts(self, student_ids):
        return set(student_id for student_id in student_ids if student_id in self.accounts)

    def change_student_password(self, student_id, current_password, new_password):
        account = self.accounts.get(student_id)
        if not account or account["password"] != current_password:
            return False
        account["password"] = new_password
        return True


class StudentManagementTests(unittest.TestCase):
    def setUp(self):
        self.students = FakeStudentStore()
        self.performance = FakePerformanceStore()
        self.accounts = FakeAccountStore()
        app = create_app(
            {"TESTING": True, "SECRET_KEY": "test", "ADMIN_PASSWORD": "admin-secret"},
            student_store=self.students,
            performance_store=self.performance,
            account_store=self.accounts,
        )
        self.client = app.test_client()
        with self.client.session_transaction() as portal_session:
            portal_session["user"] = {"username": "admin", "role": "admin"}
            portal_session["_csrf_token"] = "test-token"

    def post(self, path, data=None, **kwargs):
        values = dict(data or {})
        values["_csrf_token"] = "test-token"
        return self.client.post(path, data=values, **kwargs)

    def student_session(self, student_id):
        with self.client.session_transaction() as portal_session:
            portal_session["user"] = {
                "username": student_id,
                "role": "student",
                "student_id": student_id,
            }
            portal_session["_csrf_token"] = "test-token"

    def add_sample_student(self, student_id="STU003"):
        self.students.add_student({
            "student_id": student_id,
            "name": "Riya Das",
            "email": "riya@example.edu",
            "department": "Computing",
            "year_of_study": "1",
        })

    def test_unavailable_store_retries_initialization(self):
        app = Flask(__name__)
        attempts = 0

        class RecoveredStore:
            def list_students(self):
                return ["connected"]

        def create_store():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("Atlas is temporarily unavailable")
            return RecoveredStore()

        with self.assertLogs(app.logger.name, level="ERROR"):
            store = initialize_store(app, "test MongoDB store", "test_store", create_store)
        app.extensions["test_store"] = store

        self.assertEqual(store.list_students(), ["connected"])
        self.assertIsInstance(app.extensions["test_store"], RecoveredStore)
        self.assertEqual(attempts, 2)

    def test_login_routes_to_admin_portal(self):
        with self.client.session_transaction() as portal_session:
            portal_session.clear()
            portal_session["_csrf_token"] = "test-token"
        response = self.post(
            "/admin/login",
            {"username": "admin", "password": "admin-secret"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")

    def test_admin_login_rejects_student_account(self):
        self.accounts.set_student_password("STU003", "student-secret")
        with self.client.session_transaction() as portal_session:
            portal_session.clear()
            portal_session["_csrf_token"] = "test-token"
        response = self.post("/admin/login", {
            "username": "STU003",
            "password": "student-secret",
        })
        self.assertEqual(response.status_code, 401)

    def test_student_login_and_password_change(self):
        self.add_sample_student()
        self.accounts.set_student_password("STU003", "initial-password")
        with self.client.session_transaction() as portal_session:
            portal_session.clear()
            portal_session["_csrf_token"] = "test-token"
        response = self.post(
            "/student/login",
            {"username": "STU003", "password": "initial-password"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/portal")
        with self.client.session_transaction() as portal_session:
            portal_session["_csrf_token"] = "test-token"
        response = self.post("/account/password", data={
            "current_password": "initial-password",
            "new_password": "changed-password",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.accounts.authenticate("STU003", "initial-password"))
        self.assertEqual(
            self.accounts.authenticate("STU003", "changed-password")["role"],
            "student",
        )

    def test_add_student_and_view_admin_dashboard(self):
        response = self.post("/students/new", data={
            "student_id": "stu001", "name": "Sam Lee", "email": "sam@example.edu",
            "department": "Computing", "year_of_study": "2", "password": "student-secret",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sam Lee", response.data)
        self.assertIn("STU001", self.students.students)
        self.assertTrue(self.accounts.student_has_account("STU001"))

    def test_invalid_student_is_not_saved(self):
        response = self.post("/students/new", data={"student_id": "STU002"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.students.students, {})

    def test_academic_record_calculates_grade(self):
        self.add_sample_student()
        response = self.post("/students/STU003/records/new", data={
            "subject": "Databases", "academic_year": "2025-2026", "semester": "1",
            "exam_date": "2026-01-20", "marks": "86", "attendance_percent": "92",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.performance.records[0]["grade"], "A")
        self.assertIn(b"Databases", response.data)

    def test_out_of_range_marks_are_rejected(self):
        self.add_sample_student("STU004")
        response = self.post("/students/STU004/records/new", data={
            "subject": "Databases", "academic_year": "2025-2026", "semester": "1",
            "exam_date": "2026-01-20", "marks": "101", "attendance_percent": "92",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.performance.records, [])

    def test_student_can_only_view_and_edit_own_profile(self):
        self.add_sample_student("STU003")
        self.add_sample_student("STU004")
        self.student_session("STU003")

        self.assertEqual(self.client.get("/students/STU003").status_code, 200)
        self.assertEqual(self.client.get("/students/STU004").status_code, 403)

        response = self.post("/students/STU003/edit", data={
            "name": "Updated Name", "email": "new@example.edu",
            "department": "Computing", "year_of_study": "2",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.students.get_student("STU003")["name"], "Updated Name")
        self.assertEqual(self.post("/students/STU004/edit", data={}).status_code, 403)

    def test_student_can_edit_only_own_academic_records(self):
        self.add_sample_student("STU003")
        self.add_sample_student("STU004")
        self.performance.add_record({
            "student_id": "STU003", "academic_year": "2025-2026", "semester": 1,
            "exam_date": "2026-01-20", "subject": "Databases", "marks": 86,
            "grade": "A", "attendance_percent": 92,
        })
        self.performance.add_record({
            "student_id": "STU004", "academic_year": "2025-2026", "semester": 1,
            "exam_date": "2026-01-20", "subject": "Databases", "marks": 86,
            "grade": "A", "attendance_percent": 92,
        })
        self.student_session("STU003")
        self.assertEqual(self.client.get("/students/STU003/records/1/edit").status_code, 200)
        self.assertEqual(self.client.get("/students/STU004/records/2/edit").status_code, 403)
        response = self.post("/students/STU003/records/1/edit", data={
            "subject": "Databases", "academic_year": "2025-2026", "semester": "1",
            "exam_date": "2026-01-20", "marks": "95", "attendance_percent": "98",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.performance.records[0]["marks"], 95)

    def test_admin_only_can_create_students(self):
        self.student_session("STU003")
        self.assertEqual(self.client.get("/").status_code, 403)
        self.assertEqual(self.client.get("/students/new").status_code, 403)

    def test_admin_can_view_and_edit_any_student(self):
        self.add_sample_student("STU003")
        self.add_sample_student("STU004")
        self.assertEqual(self.client.get("/students/STU004").status_code, 200)
        response = self.post("/students/STU004/edit", data={
            "name": "Admin Updated",
            "email": "updated@example.edu",
            "department": "Computing",
            "year_of_study": "2",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.students.get_student("STU004")["name"], "Admin Updated")

    def test_missing_csrf_token_is_rejected(self):
        response = self.client.post("/students/new", data={"student_id": "STU002"})
        self.assertEqual(response.status_code, 400)

    def test_unknown_student_returns_404(self):
        self.assertEqual(self.client.get("/students/MISSING").status_code, 404)

    def test_unauthenticated_user_is_redirected_to_login(self):
        with self.client.session_transaction() as portal_session:
            portal_session.clear()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_login_choice_has_separate_portal_links(self):
        with self.client.session_transaction() as portal_session:
            portal_session.clear()
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/admin/login", response.data)
        self.assertIn(b"/student/login", response.data)


if __name__ == "__main__":
    unittest.main()
