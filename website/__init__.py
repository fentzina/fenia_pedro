from flask import Flask, app
from flask_sqlalchemy import SQLAlchemy
from os import path
import os
from flask_login import LoginManager

db = SQLAlchemy()
DB_NAME = "pedro_db.db" 

def create_app(db_uri=None):
    app = Flask(__name__)
    
    app.config['SECRET_KEY'] = 'hjshjdshjkshd kjshdjs'
    #app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123456789@localhost:5432/pedro_db'
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri or f'sqlite:///{DB_NAME}'
    
    db.init_app(app)

    from .views import views as views_blueprint
    from .auth import auth as auth_blueprint

    app.register_blueprint(views_blueprint, url_prefix='/')
    app.register_blueprint(auth_blueprint, url_prefix='/')
    
    from .models import User, ClinicalCase, Reply  

    with app.app_context():
        db.drop_all() 
        db.create_all()

        admin_email = "it@pedro.com"
        admin_exists = User.query.filter_by(email=admin_email).first()
        
        if not admin_exists:
            from werkzeug.security import generate_password_hash
            it_admin = User(
                email = admin_email,
                first_name = "IT_Admin",
                last_name = "Pedro",
                password = generate_password_hash("PedroAdmin2026!"),
                medical_license = "IT-SUPERUSER",
                role = "admin",
                is_approved = True
            )
            db.session.add(it_admin)
            db.session.commit()

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        user = User.query.get(int(id))
        if user and not user.is_approved and user.role != 'admin':
            return None
        return user

    return app
