from flask import Blueprint, render_template, request, flash, redirect, url_for
from .models import User
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user:
            if check_password_hash(user.password, password):
                if not user.is_approved and user.role != 'admin':
                    flash('The account is pending approval by the administrators. You cannot log in yet.', category='error')
                    return render_template("login.html", user=current_user)
                
                flash('Succesful log in!', category='success')
                login_user(user, remember=True)
                return redirect(url_for('views.home'))
            else:
                flash('Wrong password. Please try again.', category='error')
        else:
            flash('The email does not exist.', category='error')

    return render_template("login.html", user=current_user)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('firstName')
        last_name = request.form.get('lastName')
        medical_license = request.form.get('medical_license')

        password = request.form.get('password1')
        password_confirm = request.form.get('password2')

        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('The email is already in use.', category='error')
        elif not password or len(password) < 6:
            flash('The password must be at least 6 characters long.', category='error')
        elif password != password_confirm:
            flash('The passwords do not match.', category='error')
        else: 
            new_user = User(
                email = email, 
                first_name = first_name, 
                last_name = last_name,
                password = generate_password_hash(password),
                medical_license = medical_license,
                role = 'doctor',
                is_approved = False
            )
            db.session.add(new_user)
            db.session.commit()
        
            flash('The registration request has been submitted! You will only be able to log in once an Admin approves your account.', category='success')
            return redirect(url_for('auth.login')) 

    return render_template("sign_up.html", user=current_user)
