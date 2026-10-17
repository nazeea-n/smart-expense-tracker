import hashlib
import os
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from functools import wraps
from decimal import Decimal
from flask import Flask, render_template, request, redirect, url_for, session, flash
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key-before-deployment")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "smart_expense_tracker"),
}

# Email settings used for the "Forgot password" link.
# If MAIL_USERNAME / MAIL_PASSWORD are empty, the link is printed in the terminal instead.
MAIL_CONFIG = {
    "server": os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    "port": int(os.getenv("MAIL_PORT", "587")),
    "username": os.getenv("MAIL_USERNAME", "").strip(),
    "password": os.getenv("MAIL_PASSWORD", "").replace(" ", ""),
    "sender": os.getenv("MAIL_FROM", "").strip() or os.getenv("MAIL_USERNAME", "").strip(),
}

RESET_TOKEN_MAX_AGE = 15 * 60  # reset links stay valid for 15 minutes

CATEGORIES = [
    "Food", "Transport", "Shopping", "Bills", "Health",
    "Education", "Entertainment", "Travel", "Other"
]


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def money(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@app.template_filter("inr")
def inr(value):
    return f"₹{money(value):,.2f}"


def query_one(sql, params=()):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def query_all(sql, params=()):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()




def reset_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="password-reset")


def password_fingerprint(password_hash):
    """Short fingerprint of the current password, so a reset link works only once."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def make_reset_token(user):
    return reset_serializer().dumps({
        "uid": user["id"],
        "fp": password_fingerprint(user["password_hash"]),
    })


def read_reset_token(token):
    """Return the user for a valid, unexpired and unused reset token, otherwise None."""
    try:
        data = reset_serializer().loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except BadSignature:  # also covers expired tokens
        return None
    if not isinstance(data, dict) or "uid" not in data or "fp" not in data:
        return None
    user = query_one(
        "SELECT id, name, email, password_hash FROM users WHERE id = %s",
        (data["uid"],)
    )
    if not user or password_fingerprint(user["password_hash"]) != data["fp"]:
        return None
    return user


def send_reset_email(to_email, name, link):
    minutes = RESET_TOKEN_MAX_AGE // 60
    if not MAIL_CONFIG["username"] or not MAIL_CONFIG["password"]:
        print("\n[Pennywise] Email is not configured, so here is the reset link instead:")
        print(link + "\n")
        return

    message = EmailMessage()
    message["Subject"] = "Reset your Pennywise password"
    message["From"] = MAIL_CONFIG["sender"]
    message["To"] = to_email
    message.set_content(
        f"Hi {name},\n\n"
        "We received a request to reset your Pennywise password.\n"
        f"Open this link within {minutes} minutes to choose a new password:\n\n"
        f"{link}\n\n"
        "If you did not ask for this, you can ignore this email. Your password will not change.\n"
    )

    with smtplib.SMTP(MAIL_CONFIG["server"], MAIL_CONFIG["port"], timeout=15) as server:
        server.starttls()
        server.login(MAIL_CONFIG["username"], MAIL_CONFIG["password"])
        server.send_message(message)


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password with at least 8 characters.", "error")
            return render_template("register.html")
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                (name, email, generate_password_hash(password))
            )
            conn.commit()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
        except Error as exc:
            conn.rollback()
            if getattr(exc, "errno", None) == 1062:
                flash("An account with that email already exists.", "error")
            else:
                app.logger.exception("Registration failed")
                flash("Could not create your account. Check the database setup and try again.", "error")
        finally:
            cur.close()
            conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        try:
            user = query_one("SELECT id, name, email, password_hash FROM users WHERE email = %s", (email,))
        except Error:
            flash("Database connection failed. Check your .env settings and SQL setup.", "error")
            return render_template("login.html")
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        try:
            user = None
            if email:
                user = query_one(
                    "SELECT id, name, email, password_hash FROM users WHERE email = %s",
                    (email,)
                )
            if user:
                link = url_for("reset_password", token=make_reset_token(user), _external=True)
                send_reset_email(user["email"], user["name"], link)
        except Error:
            app.logger.exception("Forgot password: database error")
            flash("Database connection failed. Check your .env settings and SQL setup.", "error")
            return render_template("forgot_password.html")
        except (smtplib.SMTPException, OSError):
            app.logger.exception("Forgot password: could not send the email")

        # Same message whether or not the email exists, so nobody can check who has an account.
        flash("If that email is registered, a reset link has been sent. It is valid for 15 minutes.", "info")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        user = read_reset_token(token)
    except Error:
        app.logger.exception("Reset password: database error")
        flash("Database connection failed. Check your .env settings and SQL setup.", "error")
        return redirect(url_for("login"))

    if not user:
        flash("This reset link is invalid or has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Your new password must be at least 8 characters.", "error")
            return render_template("reset_password.html")
        if password != confirm:
            flash("The two passwords do not match.", "error")
            return render_template("reset_password.html")

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (generate_password_hash(password), user["id"])
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        session.clear()
        flash("Password updated. Please log in with your new password.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html")


@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    today = date.today()
    month_start = today.replace(day=1)
    total = query_one(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id=%s AND expense_date BETWEEN %s AND %s",
        (uid, month_start, today)
    )["total"]
    count = query_one(
        "SELECT COUNT(*) AS total FROM expenses WHERE user_id=%s AND expense_date BETWEEN %s AND %s",
        (uid, month_start, today)
    )["total"]
    budget_row = query_one("SELECT amount FROM budgets WHERE user_id=%s AND budget_month=%s", (uid, month_start))
    budget = budget_row["amount"] if budget_row else Decimal("0")
    recent = query_all(
        "SELECT id, title, category, amount, expense_date FROM expenses WHERE user_id=%s ORDER BY expense_date DESC, id DESC LIMIT 6",
        (uid,)
    )
    categories = query_all(
        "SELECT category, SUM(amount) AS total FROM expenses WHERE user_id=%s AND expense_date BETWEEN %s AND %s GROUP BY category ORDER BY total DESC",
        (uid, month_start, today)
    )
    daily = query_all(
        "SELECT expense_date, SUM(amount) AS total FROM expenses WHERE user_id=%s AND expense_date BETWEEN %s AND %s GROUP BY expense_date ORDER BY expense_date",
        (uid, month_start, today)
    )
    return render_template(
        "dashboard.html", total=total, count=count, budget=budget,
        remaining=money(budget)-money(total), recent=recent, categories=categories,
        daily=daily, today=today, month_label=today.strftime("%B %Y"),
        category_labels=[r["category"] for r in categories],
        category_values=[money(r["total"]) for r in categories],
        daily_labels=[r["expense_date"].strftime("%d %b") for r in daily],
        daily_values=[money(r["total"]) for r in daily],
    )


@app.route("/expenses")
@login_required
def expenses():
    uid = session["user_id"]
    month = request.args.get("month", "").strip()
    category = request.args.get("category", "").strip()
    sql = "SELECT id, title, category, amount, expense_date, notes FROM expenses WHERE user_id=%s"
    params = [uid]
    if month:
        try:
            datetime.strptime(month, "%Y-%m")
            sql += " AND DATE_FORMAT(expense_date, '%Y-%m')=%s"
            params.append(month)
        except ValueError:
            flash("Invalid month filter.", "error")
    if category in CATEGORIES:
        sql += " AND category=%s"
        params.append(category)
    sql += " ORDER BY expense_date DESC, id DESC"
    rows = query_all(sql, tuple(params))
    return render_template("expenses.html", expenses=rows, categories=CATEGORIES, selected_month=month, selected_category=category)


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "")
        amount_text = request.form.get("amount", "").strip()
        expense_date = request.form.get("expense_date", "")
        notes = request.form.get("notes", "").strip() or None
        try:
            amount = Decimal(amount_text)
            parsed_date = datetime.strptime(expense_date, "%Y-%m-%d").date()
            if amount <= 0 or not title or category not in CATEGORIES:
                raise ValueError
        except (ValueError, ArithmeticError):
            flash("Please enter a title, valid category, positive amount and valid date.", "error")
            return render_template("expense_form.html", categories=CATEGORIES, expense=None, today=date.today().isoformat(), page_title="Add expense")
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO expenses (user_id, title, category, amount, expense_date, notes) VALUES (%s,%s,%s,%s,%s,%s)",
                (session["user_id"], title, category, amount, parsed_date, notes)
            )
            conn.commit()
            flash("Expense added successfully.", "success")
            return redirect(url_for("expenses"))
        finally:
            cur.close()
            conn.close()
    return render_template("expense_form.html", categories=CATEGORIES, expense=None, today=date.today().isoformat(), page_title="Add expense")


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    uid = session["user_id"]
    expense = query_one("SELECT * FROM expenses WHERE id=%s AND user_id=%s", (expense_id, uid))
    if not expense:
        flash("Expense not found.", "error")
        return redirect(url_for("expenses"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "")
        amount_text = request.form.get("amount", "").strip()
        expense_date = request.form.get("expense_date", "")
        notes = request.form.get("notes", "").strip() or None
        try:
            amount = Decimal(amount_text)
            parsed_date = datetime.strptime(expense_date, "%Y-%m-%d").date()
            if amount <= 0 or not title or category not in CATEGORIES:
                raise ValueError
        except (ValueError, ArithmeticError):
            flash("Please enter valid expense details.", "error")
            return render_template("expense_form.html", categories=CATEGORIES, expense=expense, today=date.today().isoformat(), page_title="Edit expense")
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE expenses SET title=%s, category=%s, amount=%s, expense_date=%s, notes=%s WHERE id=%s AND user_id=%s",
                (title, category, amount, parsed_date, notes, expense_id, uid)
            )
            conn.commit()
            flash("Expense updated.", "success")
            return redirect(url_for("expenses"))
        finally:
            cur.close()
            conn.close()
    return render_template("expense_form.html", categories=CATEGORIES, expense=expense, today=date.today().isoformat(), page_title="Edit expense")


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM expenses WHERE id=%s AND user_id=%s", (expense_id, session["user_id"]))
        conn.commit()
        flash("Expense deleted.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("expenses"))


@app.route("/budget", methods=["GET", "POST"])
@login_required
def budget():
    uid = session["user_id"]
    month_start = date.today().replace(day=1)
    if request.method == "POST":
        try:
            amount = Decimal(request.form.get("amount", ""))
            if amount < 0:
                raise ValueError
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO budgets (user_id, budget_month, amount) VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE amount=VALUES(amount)",
                (uid, month_start, amount)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash("Monthly budget saved.", "success")
            return redirect(url_for("budget"))
        except (ValueError, ArithmeticError):
            flash("Enter a valid budget amount.", "error")
    row = query_one("SELECT amount FROM budgets WHERE user_id=%s AND budget_month=%s", (uid, month_start))
    spent = query_one(
        "SELECT COALESCE(SUM(amount),0) AS total FROM expenses WHERE user_id=%s AND expense_date >= %s AND expense_date <= %s",
        (uid, month_start, date.today())
    )["total"]
    amount = row["amount"] if row else Decimal("0")
    percentage = min(100, (money(spent) / money(amount) * 100)) if money(amount) > 0 else 0
    return render_template("budget.html", budget=amount, spent=spent, remaining=money(amount)-money(spent), percentage=percentage, month_label=date.today().strftime("%B %Y"))


@app.route("/report")
@login_required
def report():
    uid = session["user_id"]
    start = request.args.get("start", date.today().replace(day=1).isoformat())
    end = request.args.get("end", date.today().isoformat())
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
        if start_date > end_date:
            raise ValueError
    except ValueError:
        flash("Choose a valid date range.", "error")
        return redirect(url_for("report"))
    rows = query_all(
        "SELECT title, category, amount, expense_date, notes FROM expenses WHERE user_id=%s AND expense_date BETWEEN %s AND %s ORDER BY expense_date DESC",
        (uid, start_date, end_date)
    )
    total = sum((money(row["amount"]) for row in rows), 0.0)
    return render_template("report.html", rows=rows, total=total, start=start, end=end)


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", message="Something went wrong. Check the terminal for details."), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "true").lower() == "true")
