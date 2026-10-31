# Student Information and Academic Performance Management

A beginner-friendly Flask project that stores student profiles and academic performance records in MongoDB. The web interface supports student search, profile registration, performance history, adding marks/attendance, and persistent light and dark themes.

## Requirements

- Docker Desktop with Docker Compose

## Run locally

In VS Code, open **Terminal > New Terminal**. Make sure the prompt shows this project folder (`D:\NoSQL`), then run:

```powershell
docker compose up -d
```

This starts the Flask app and MongoDB. When the web container reports that Flask is running, open `http://127.0.0.1:5000`.

### Admin and student portals

The sign-in page separates two roles. The admin signs in using `ADMIN_USERNAME` and `ADMIN_PASSWORD` from the private root `.env` file and can search, view, and edit every student and academic record. Students sign in using their student ID and a password created by the admin. A student can view and edit only their own profile and academic records. Role checks are enforced on the server, and portal forms use CSRF tokens.

Set a unique, strong `ADMIN_PASSWORD` and `FLASK_SECRET_KEY` in `.env` before starting the app. The initial admin account is created in MongoDB on first startup. In the admin portal, registering a student creates their account; for existing profiles, open a profile and set/reset the student password there. Share student passwords privately. Passwords are stored as hashes in the MongoDB `accounts` collection.

### Use MongoDB Atlas

The default Docker setup uses its local MongoDB container. To use Atlas instead, create a root-level `.env` file (for example, copy `.env.example`) and set `MONGO_URI` to the Atlas connection string from your cluster's **Connect > Drivers** page. Keep `MONGO_DATABASE=student_management`, and do not commit or share `.env`; it is git-ignored. URL-encode any reserved characters in the database username or password, and allow your machine's public IP in the Atlas Network Access settings.

Then recreate the app so the new URI is loaded:

```powershell
docker compose up -d --build
```

The Flask app will connect to Atlas; the local MongoDB container will still start but will not be used by the app. Do not put Atlas credentials directly in `docker-compose.yml`.

Docker containers can use a different public egress IP from the host machine. If Atlas connects from the host but not from the web container, add the container's specific egress IP as a separate `/32` entry under Atlas **Security > Network Access**; do not allow `0.0.0.0/0`. If you prefer to connect from the host instead, stop the Docker web service and run Flask locally:

```powershell
docker compose stop web
python run.py
```

The local Flask process reads the root `.env` file and connects directly to Atlas.

To load sample records, open a second VS Code terminal in `D:\NoSQL` and run:

```powershell
docker compose exec web python seed.py
```

Seed records are safe to rerun. Student IDs and academic record keys are checked before inserting.

If you want to run Flask outside Docker, install `requirements.txt` in a Python virtual environment, copy `.env.example` to `.env`, start MongoDB with `docker compose up -d mongodb` (unless using Atlas), and run `python run.py` from `D:\NoSQL`. In that case, the example `.env` addresses localhost-mapped database ports.

To stop the app and databases, press `Ctrl+C` in the first terminal or run `docker compose down` in another terminal. To remove local database data as well, run `docker compose down -v` (this deletes the demo data).

## Run tests

The unit tests use in-memory fake stores, so Docker is not required. Run them in a Python environment with the requirements installed:

```powershell
python -m unittest discover -s tests -v
```

## Data model

### MongoDB: `student_management.students`

Example document:

```json
{
  "student_id": "STU2026001",
  "name": "Aarav Patel",
  "email": "aarav.patel@example.edu",
  "department": "Computer Science",
  "year_of_study": "3"
}
```

`student_id` has a unique index and is the profile key used to associate academic records.

If you already have profiles from an earlier version, remove the retired `course` field from existing MongoDB documents with:

```powershell
docker compose exec mongodb mongosh --quiet student_management --eval "db.students.updateMany({}, {`$unset: {course: 1}})"
```

### MongoDB: `student_management.academic_records`

Academic records are stored as documents in `academic_records`. A unique compound index on `student_id`, `academic_year`, `semester`, `exam_date`, and `subject` prevents duplicate entries. Each record also stores marks, calculated grade, and attendance percentage.

### MongoDB: `student_management.accounts`

Portal accounts store a username, password hash, and role. Student accounts are linked to their student ID. The initial admin account is provisioned from environment variables and student accounts are created or reset through the admin portal.

## Project layout

- `student_app/routes.py`: Flask views, validation, grade calculation
- `student_app/stores.py`: MongoDB access
- `student_app/templates/`: server-rendered pages
- `student_app/static/style.css`: responsive styling
- `docker-compose.yml`: local database services
- `seed.py`: repeatable sample data loader
- `tests/test_app.py`: database-independent route tests

## Viva walkthrough

1. Start MongoDB with Docker Compose, or configure MongoDB Atlas.
2. Start the Flask app and register a student. Explain that the profile document goes to MongoDB.
3. Open that student's profile and add a subject result. The profile and academic record are both saved in MongoDB collections.
4. Return to the profile. The app reads the profile and academic history from MongoDB and displays them together.

## Viva questions to prepare

1. **Why use MongoDB?** Its document model stores flexible student profiles and academic records in one database.
2. **What is a MongoDB document and collection?** A document is a BSON record; a collection is a group of documents, similar in role to a relational table but with flexible fields.
3. **How are academic records associated with a student?** Each record stores the student's `student_id`; a compound unique index prevents duplicate subject results.
4. **How is the grade calculated?** The Flask route maps the numeric score to a grade band before persisting the academic record.
5. **What would you improve for production?** Authentication and role-based access, stronger validation, migration/schema management, audit trails, encrypted secrets, backups, pagination, and logging/monitoring.

## Important note

This is an academic demonstration, not a production student-information system. Use synthetic data. Do not store real student records without institutional approval, access controls, and privacy/security review.
