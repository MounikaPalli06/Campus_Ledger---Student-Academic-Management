from datetime import date
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .stores import DuplicateRecordError, DuplicateStudentError

bp = Blueprint("main", __name__)


def stores():
    return (
        current_app.extensions["student_store"],
        current_app.extensions["performance_store"],
        current_app.extensions["account_store"],
    )


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if session.get("user", {}).get("role") != "admin":
            abort(403)
        return function(*args, **kwargs)
    return wrapped


def can_access_student(student_id):
    user = session.get("user", {})
    if user.get("role") == "admin":
        return
    if user.get("role") != "student" or user.get("student_id") != student_id:
        abort(403)


def dashboard_for_user():
    if session.get("user", {}).get("role") == "admin":
        return url_for("main.dashboard")
    return url_for("main.student_dashboard")


def calculate_grade(marks):
    if marks >= 90:
        return "A+"
    if marks >= 80:
        return "A"
    if marks >= 70:
        return "B"
    if marks >= 60:
        return "C"
    if marks >= 50:
        return "D"
    return "F"


def profile_from_form(student_id=None):
    student = {
        "student_id": student_id or request.form.get("student_id", "").strip().upper(),
        "name": request.form.get("name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "department": request.form.get("department", "").strip(),
        "year_of_study": request.form.get("year_of_study", "").strip(),
    }
    if not all(student.values()):
        return student, "Complete every field before saving."
    if "@" not in student["email"]:
        return student, "Enter a valid email address."
    if student["year_of_study"] not in {"1", "2", "3", "4", "5", "6"}:
        return student, "Year of study must be between 1 and 6."
    return student, None


def get_student_or_respond(student_id):
    student_store, _, _ = stores()
    try:
        student = student_store.get_student(student_id)
    except Exception:
        current_app.logger.exception("Could not load student from MongoDB")
        flash("MongoDB is unavailable. The student profile could not be loaded.", "error")
        return None, (render_template("not_found.html", student_id=student_id), 503)
    if not student:
        return None, (render_template("not_found.html", student_id=student_id), 404)
    return student, None


@bp.get("/login")
def login():
    if session.get("user"):
        return redirect(dashboard_for_user())
    return render_template("login_choice.html")


def authenticate_for_role(role):
    if session.get("user"):
        return redirect(dashboard_for_user())
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            account = current_app.extensions["account_store"].authenticate(username, password)
        except Exception:
            current_app.logger.exception("Could not authenticate portal user")
            flash("Sign-in is temporarily unavailable. Please try again.", "error")
            return render_template("login.html", role=role), 503
        if not account or account.get("role") != role:
            flash("The user ID or password is incorrect.", "error")
            return render_template("login.html", role=role), 401
        session.clear()
        session["user"] = account
        next_url = request.args.get("next", "")
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(dashboard_for_user())
    return render_template("login.html", role=role)


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return authenticate_for_role("admin")


@bp.route("/student/login", methods=["GET", "POST"])
def student_login():
    return authenticate_for_role("student")


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("main.login"))


@bp.route("/account/password", methods=["GET", "POST"])
def change_password():
    user = session.get("user", {})
    if user.get("role") != "student":
        abort(403)
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        if len(new_password) < 8:
            flash("Your new password must be at least 8 characters.", "error")
            return render_template("change_password.html"), 400
        try:
            changed = current_app.extensions["account_store"].change_student_password(
                user["student_id"], current_password, new_password
            )
        except Exception:
            current_app.logger.exception("Could not change student password")
            flash("The password could not be changed. Please try again.", "error")
            return render_template("change_password.html"), 503
        if not changed:
            flash("Your current password is incorrect.", "error")
            return render_template("change_password.html"), 400
        flash("Your password was changed.", "success")
        return redirect(url_for("main.student_dashboard"))
    return render_template("change_password.html")


@bp.get("/")
@admin_required
def dashboard():
    student_store, _, account_store = stores()
    search = request.args.get("q", "").strip()
    try:
        students = student_store.list_students(search)
        student_ids = [student["student_id"] for student in students]
        accounts = account_store.student_accounts(student_ids)
        for student in students:
            student["has_account"] = student["student_id"] in accounts
    except Exception:
        current_app.logger.exception("Could not load students from MongoDB")
        flash("MongoDB is unavailable. Start the database and refresh.", "error")
        students = []
    departments = {student["department"] for student in students}
    year_levels = {student["year_of_study"] for student in students}
    return render_template(
        "dashboard.html",
        students=students,
        search=search,
        department_count=len(departments),
        year_level_count=len(year_levels),
    )


@bp.get("/portal")
def student_dashboard():
    user = session.get("user", {})
    if user.get("role") == "admin":
        return redirect(url_for("main.dashboard"))
    student_id = user.get("student_id", "")
    student, error_response = get_student_or_respond(student_id)
    if error_response:
        return error_response
    try:
        records = current_app.extensions["performance_store"].list_records(student_id)
    except Exception:
        current_app.logger.exception("Could not load academic records from MongoDB")
        flash("MongoDB is unavailable. Academic records could not be loaded.", "error")
        records = []
    average = round(sum(record["marks"] for record in records) / len(records), 1) if records else None
    return render_template(
        "student_portal.html", student=student, records=records, average=average
    )


@bp.route("/students/new", methods=["GET", "POST"])
@admin_required
def add_student():
    if request.method == "POST":
        student, error = profile_from_form()
        password = request.form.get("password", "")
        if not error and len(password) < 8:
            error = "Set an initial student password with at least 8 characters."
        if error:
            flash(error, "error")
            return render_template("student_form.html", student=student), 400
        student_store, _, account_store = stores()
        try:
            student_store.add_student(student)
            account_store.set_student_password(student["student_id"], password)
        except DuplicateStudentError:
            flash("That student ID already exists.", "error")
            return render_template("student_form.html", student=student), 409
        except Exception:
            current_app.logger.exception("Could not save student or student account")
            flash("MongoDB could not save the student. Check the database connection.", "error")
            return render_template("student_form.html", student=student), 503
        flash("Student profile and portal account created.", "success")
        return redirect(url_for("main.student_detail", student_id=student["student_id"]))
    return render_template("student_form.html", student={})


@bp.route("/students/<student_id>/edit", methods=["GET", "POST"])
def edit_student(student_id):
    can_access_student(student_id)
    student, error_response = get_student_or_respond(student_id)
    if error_response:
        return error_response
    if request.method == "POST":
        updated, error = profile_from_form(student_id)
        if error:
            flash(error, "error")
            return render_template("student_edit.html", student=updated), 400
        try:
            current_app.extensions["student_store"].update_student(student_id, updated)
        except Exception:
            current_app.logger.exception("Could not update student profile in MongoDB")
            flash("MongoDB could not update the profile. Please try again.", "error")
            return render_template("student_edit.html", student=updated), 503
        flash("Your student profile was updated.", "success")
        return redirect(url_for("main.student_detail", student_id=student_id))
    return render_template("student_edit.html", student=student)


@bp.post("/students/<student_id>/account")
@admin_required
def set_student_account(student_id):
    student, error_response = get_student_or_respond(student_id)
    if error_response:
        return error_response
    password = request.form.get("password", "")
    if len(password) < 8:
        flash("Student passwords must be at least 8 characters.", "error")
        return redirect(url_for("main.student_detail", student_id=student_id))
    try:
        current_app.extensions["account_store"].set_student_password(student_id, password)
    except Exception:
        current_app.logger.exception("Could not set student portal password")
        flash("MongoDB could not save the student account.", "error")
        return redirect(url_for("main.student_detail", student_id=student_id))
    flash("Student portal password set. Share it with the student securely.", "success")
    return redirect(url_for("main.student_detail", student_id=student["student_id"]))


@bp.get("/students/<student_id>")
def student_detail(student_id):
    can_access_student(student_id)
    student, error_response = get_student_or_respond(student_id)
    if error_response:
        return error_response
    _, performance_store, _ = stores()
    try:
        records = performance_store.list_records(student_id)
    except Exception:
        current_app.logger.exception("Could not load academic records from MongoDB")
        flash("MongoDB is unavailable. Academic records could not be loaded.", "error")
        records = []
    records.sort(key=lambda record: (
        record["academic_year"], record["semester"], record["exam_date"], record["subject"]
    ), reverse=True)
    average = round(sum(record["marks"] for record in records) / len(records), 1) if records else None
    return render_template(
        "student_detail.html", student=student, records=records, average=average
    )


def record_from_form(student_id):
    form = request.form
    try:
        marks = float(form.get("marks", ""))
        attendance = float(form.get("attendance_percent", ""))
        semester = int(form.get("semester", ""))
        exam_date = date.fromisoformat(form.get("exam_date", ""))
    except (TypeError, ValueError):
        return None, "Enter valid marks, attendance, semester, and exam date."
    subject = form.get("subject", "").strip()
    academic_year = form.get("academic_year", "").strip()
    if not subject or not academic_year:
        return None, "Subject and academic year are required."
    if not 0 <= marks <= 100 or not 0 <= attendance <= 100 or semester not in range(1, 9):
        return None, "Marks and attendance must be 0-100; semester must be 1-8."
    return {
        "student_id": student_id,
        "academic_year": academic_year,
        "semester": semester,
        "exam_date": exam_date.isoformat(),
        "subject": subject,
        "marks": marks,
        "grade": calculate_grade(marks),
        "attendance_percent": attendance,
    }, None


@bp.route("/students/<student_id>/records/new", methods=["GET", "POST"])
def add_record(student_id):
    can_access_student(student_id)
    student, error_response = get_student_or_respond(student_id)
    if error_response:
        return error_response
    if request.method == "POST":
        record, error = record_from_form(student_id)
        if error:
            flash(error, "error")
            return render_template("record_form.html", student=student, record={}), 400
        try:
            current_app.extensions["performance_store"].add_record(record)
        except DuplicateRecordError:
            flash("An academic record with that subject and exam date already exists.", "error")
            return render_template("record_form.html", student=student, record=record), 409
        except Exception:
            current_app.logger.exception("Could not save academic record to MongoDB")
            flash("MongoDB could not save the record. Check the database connection.", "error")
            return render_template("record_form.html", student=student, record=record), 503
        flash("Academic record saved.", "success")
        return redirect(url_for("main.student_detail", student_id=student_id))
    return render_template("record_form.html", student=student, record={})


@bp.route("/students/<student_id>/records/<record_id>/edit", methods=["GET", "POST"])
def edit_record(student_id, record_id):
    can_access_student(student_id)
    student, error_response = get_student_or_respond(student_id)
    if error_response:
        return error_response
    performance_store = current_app.extensions["performance_store"]
    try:
        record = performance_store.get_record(student_id, record_id)
    except Exception:
        current_app.logger.exception("Could not load academic record from MongoDB")
        flash("MongoDB could not load the academic record.", "error")
        return redirect(url_for("main.student_detail", student_id=student_id))
    if not record:
        abort(404)
    if request.method == "POST":
        updated, error = record_from_form(student_id)
        if error:
            flash(error, "error")
            return render_template(
                "record_form.html", student=student, record=record, editing=True
            ), 400
        try:
            performance_store.update_record(student_id, record_id, updated)
        except DuplicateRecordError:
            flash("Another record already uses that subject and exam date.", "error")
            return render_template(
                "record_form.html", student=student, record=updated, editing=True
            ), 409
        except Exception:
            current_app.logger.exception("Could not update academic record in MongoDB")
            flash("MongoDB could not update the academic record.", "error")
            return render_template(
                "record_form.html", student=student, record=updated, editing=True
            ), 503
        flash("Academic record updated.", "success")
        return redirect(url_for("main.student_detail", student_id=student_id))
    return render_template("record_form.html", student=student, record=record, editing=True)
