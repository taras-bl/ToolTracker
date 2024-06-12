from flask import Flask, render_template, request, redirect, url_for, session, flash, get_flashed_messages
from flask_sqlalchemy import SQLAlchemy
import qrcode
import os
import cv2
from pyzbar.pyzbar import decode
import random
import string
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Tool(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    qr_code = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(120), nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tool_id = db.Column(db.Integer, db.ForeignKey('tool.id'), nullable=False)
    borrow_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    return_date = db.Column(db.DateTime, nullable=True)

with app.app_context():
    db.create_all()

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

def generate_qr_code(tool):
    security_token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    qr_data = f"{tool.id}:{tool.name}:{security_token}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    
    qr_code_dir = os.path.join('static', 'qr_codes')
    os.makedirs(qr_code_dir, exist_ok=True)
    
    qr_code_filename = f"{tool.name}_{tool.id}_{tool.location.replace(' ', '_')}_QRcode.png"
    qr_code_path = os.path.join(qr_code_dir, qr_code_filename)
    
    img.save(qr_code_path)
    return qr_code_path

def add_tool(name, location):
    new_tool = Tool(name=name, location=location, qr_code="placeholder")
    db.session.add(new_tool)
    db.session.commit()
    
    qr_code = generate_qr_code(new_tool)
    new_tool.qr_code = qr_code
    db.session.commit()
    print(f"Tool '{name}' added with QR code.")

def remove_tool(tool_id):
    tool = Tool.query.get(tool_id)
    if tool:
        db.session.delete(tool)
        db.session.commit()
        print(f"Tool ID '{tool_id}' removed.")
    else:
        print(f"Tool ID '{tool_id}' not found.")

def list_tools():
    tools = Tool.query.all()
    for tool in tools:
        print(f"Tool ID: {tool.id}, Name: {tool.name}, Location: {tool.location}, QR Code: {tool.qr_code}")

def identify_tool_from_qr_code(file_path):
    img = cv2.imread(file_path)
    decoded_objects = decode(img)
    for obj in decoded_objects:
        qr_data = obj.data.decode('utf-8')
        tool_id = qr_data.split(':')[0]
        tool = Tool.query.get(tool_id)
        if tool:
            print(f"QR code corresponds to Tool ID: {tool.id}, Name: {tool.name}")
            return tool
    print("No matching tool found for this QR code.")
    return None

def regenerate_qr_codes():
    tools = Tool.query.all()
    for tool in tools:
        qr_code = generate_qr_code(tool)
        tool.qr_code = qr_code
    db.session.commit()
    print("QR codes regenerated for all tools.")

def add_user(username, password):
    if User.query.filter_by(username=username).first():
        print('Username already exists.')
        return
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f"User '{username}' added.")

def remove_user(user_id):
    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        print(f"User ID '{user_id}' removed.")
    else:
        print(f"User ID '{user_id}' not found.")

def list_users():
    users = User.query.all()
    for user in users:
        print(f"User ID: {user.id}, Username: {user.username}")

@app.route('/')
def index():
    borrowed_items = db.session.query(Transaction, Tool, User) \
                               .join(Tool, Transaction.tool_id == Tool.id) \
                               .join(User, Transaction.user_id == User.id) \
                               .filter(Transaction.return_date.is_(None)) \
                               .all()
    return render_template('index.html', borrowed_items=borrowed_items)

@app.route('/inventory')
def inventory():
    tools = Tool.query.all()
    return render_template('inventory.html', tools=tools)

@app.route('/lend_qr', methods=['POST'])
def lend_qr():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    qr_data = request.form['qr_data']
    tool = Tool.query.filter_by(name=qr_data).first()
    if tool:
        active_transaction = Transaction.query.filter_by(tool_id=tool.id, return_date=None).first()
        if active_transaction:
            flash('Tool is already lent out', 'danger')
        else:
            user_id = session['user_id']
            transaction = Transaction(user_id=user_id, tool_id=tool.id, borrow_date=datetime.datetime.utcnow())
            db.session.add(transaction)
            db.session.commit()
            flash('Tool lent successfully', 'success')
    else:
        flash('Tool not found', 'danger')
    
    return redirect(url_for('lend'))

@app.route('/return_qr', methods=['POST'])
def return_qr():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    qr_data = request.form['qr_data']
    tool = Tool.query.filter_by(name=qr_data).first()
    if tool:
        transaction = Transaction.query.filter_by(tool_id=tool.id, return_date=None).first()
        if transaction:
            transaction.return_date = datetime.datetime.utcnow()
            db.session.commit()
            flash('Tool returned successfully', 'success')
        else:
            flash('No active lending record found for this tool', 'danger')
    else:
        flash('Tool not found', 'danger')
    
    return redirect(url_for('return_tool'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        print(f"Attempting login with username: {username}")
        user = User.query.filter_by(username=username).first()
        if user:
            print(f"User found: {user.username}")
            if user.check_password(password):
                session['user_id'] = user.id
                flash('Login successful', 'success')
                return redirect(url_for('lend'))
            else:
                flash('Incorrect password', 'danger')
        else:
            print("User not found")
            flash('Username not found', 'danger')
    return render_template('login.html')

@app.route('/lend', methods=['GET', 'POST'])
def lend():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        tool_id = request.form['tool_id']
        user_id = session['user_id']
        transaction = Transaction(user_id=user_id, tool_id=tool_id, borrow_date=datetime.datetime.utcnow())
        db.session.add(transaction)
        db.session.commit()
        flash('Tool lent successfully', 'success')
    
    lent_out_tools = db.session.query(Transaction.tool_id).filter(Transaction.return_date.is_(None)).subquery()
    available_tools = Tool.query.filter(Tool.id.not_in(lent_out_tools.select())).all()

    borrowed_tools = db.session.query(Tool).join(Transaction).filter(Transaction.return_date.is_(None)).all()

    return render_template('lend.html', tools=available_tools, borrowed_tools=borrowed_tools)

@app.route('/return', methods=['GET', 'POST'])
def return_tool():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        tool_id = request.form['tool_id']
        transaction = Transaction.query.filter_by(tool_id=tool_id, return_date=None).first()
        if transaction:
            transaction.return_date = datetime.datetime.utcnow()
            db.session.commit()
            flash('Tool returned successfully')

    transactions = db.session.query(Transaction, Tool).join(Tool).filter(Transaction.return_date.is_(None)).all()
    borrowed_tools = [transaction.Tool for transaction in transactions]
    
    return render_template('return.html', transactions=transactions, borrowed_tools=borrowed_tools)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out')
    return redirect(url_for('login'))

def add_test_data():
    test_users = [
        {"username": "Alice", "password": "password1"},
        {"username": "Bob", "password": "password2"},
        {"username": "Charlie", "password": "password3"},
    ]

    test_tools = [
        {"name": "Hammer", "location": "Drawer 1"},
        {"name": "Screwdriver", "location": "Drawer 2"},
        {"name": "Wrench", "location": "Drawer 3"},
        {"name": "Drill", "location": "Under Desk 1"},
        {"name": "Saw", "location": "Drawer 4"},
        {"name": "Pliers", "location": "Drawer 5"},
        {"name": "Tape Measure", "location": "Drawer 6"},
        {"name": "Level", "location": "Drawer 7"},
        {"name": "Chisel", "location": "Drawer 8"},
        {"name": "Utility Knife", "location": "Under Desk 2"},
    ]

    for user in test_users:
        add_user(user["username"], user["password"])

    for tool in test_tools:
        add_tool(tool["name"], tool["location"])

    print("Test data added: 3 users and 10 tools.")

def run_console():
    try:
        with app.app_context():
            while True:
                print("\nTool Management System")
                print("1. Add Tool")
                print("2. Remove Tool")
                print("3. List Tools")
                print("4. Add User")
                print("5. Remove User")
                print("6. List Users")
                print("7. Identify Tool")
                print("10. Add Test Data")
                print("11. Regenerate QR Codes")
                print("12. Exit")
                choice = input("Enter your choice: ")

                if choice == '1':
                    name = input("Enter tool name: ")
                    location = input("Enter tool location: ")
                    add_tool(name, location)
                elif choice == '2':
                    tool_id = int(input("Enter tool ID to remove: "))
                    remove_tool(tool_id)
                elif choice == '3':
                    list_tools()
                elif choice == '4':
                    username = input("Enter user name: ")
                    password = input("Enter password: ")
                    add_user(username, password)
                elif choice == '5':
                    user_id = int(input("Enter user ID to remove: "))
                    remove_user(user_id)
                elif choice == '6':
                    list_users()
                elif choice == '7':
                    filename = input("Enter QR code filename: ")
                    file_path = os.path.join('static', 'qr_codes', filename)
                    print(f"Reading QR code from: {file_path}")
                    identify_tool_from_qr_code(file_path)
                elif choice == '10':
                    add_test_data()
                elif choice == '11':
                    regenerate_qr_codes()
                elif choice == '12':
                    shutdown_server()
                    break
                else:
                    print("Invalid choice. Please try again.")
    except KeyboardInterrupt:
        shutdown_server()

if __name__ == '__main__':
    console_thread = threading.Thread(target=run_console)
    console_thread.start()

    context = ('certs/certificate.pem', 'certs/key.pem')
    app.run(debug=True, ssl_context=context, host='0.0.0.0', port=5000)