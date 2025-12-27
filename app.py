from flask import Flask, render_template, request, redirect, url_for, send_file, session
import csv
import os
import random
import datetime
import io
import zipfile
from collections import deque, Counter

app = Flask(__name__)
app.secret_key = "medical_super_secret_key"

# --- FILES ---
PATIENTS_FILE = "patients.csv"
DOCTORS_FILE = "doctors.csv"
LOGS_FILE = "logs.csv"

# --- GLOBAL VARIABLES ---
all_patients = []
all_doctors = []
all_logs = []
TOTAL_BEDS = 20
beds_status = ["Free"] * TOTAL_BEDS

# ==========================================
#  DSA: MAX-HEAP (Priority Queue)
# ==========================================
class MaxHeap:
    def __init__(self): self.heap = []
    def parent(self, i): return (i - 1) // 2
    def left_child(self, i): return 2 * i + 1
    def right_child(self, i): return 2 * i + 2
    def swap(self, i, j): self.heap[i], self.heap[j] = self.heap[j], self.heap[i]

    def insert(self, patient):
        self.heap.append(patient)
        self._sift_up(len(self.heap) - 1)

    def extract_max(self):
        if not self.heap: return None
        root = self.heap[0]
        last = self.heap.pop()
        if self.heap:
            self.heap[0] = last
            self._sift_down(0)
        return root

    def _sift_up(self, i):
        while i > 0 and self.heap[i].priority_score > self.heap[self.parent(i)].priority_score:
            self.swap(i, self.parent(i)); i = self.parent(i)

    def _sift_down(self, i):
        max_index = i
        l = self.left_child(i); r = self.right_child(i)
        if l < len(self.heap) and self.heap[l].priority_score > self.heap[max_index].priority_score: max_index = l
        if r < len(self.heap) and self.heap[r].priority_score > self.heap[max_index].priority_score: max_index = r
        if i != max_index: self.swap(i, max_index); self._sift_down(max_index)
    
    def __len__(self): return len(self.heap)

waiting_queue = MaxHeap()

# ==========================================
#  CLASSES
# ==========================================
class Patient:
    def __init__(self, p_id, name, age, disease, status="Waiting", priority="Normal", room="-", severity="Low", doc="General", time="-", est_days=1):
        self.id = int(p_id); self.name = name; self.age = int(age); self.disease = disease
        self.status = status; self.priority = priority; self.room = room
        self.severity = severity; self.doc = doc; self.time = time; self.est_days = int(est_days)
        self.priority_score = 100 if priority == "Critical" else (50 if severity == "Moderate" else 10)
        if self.age > 60: self.priority_score += 5

class Doctor:
    def __init__(self, name, specialty, room, keywords):
        self.name = name; self.specialty = specialty; self.room = room; self.keywords = keywords

class Log:
    def __init__(self, time, user, action, details):
        self.time = time; self.user = user; self.action = action; self.details = details

# ==========================================
#  HELPER FUNCTIONS
# ==========================================
def log_activity(action, details):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = session.get('user', 'System')
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'w', newline='') as f: csv.writer(f).writerow(["Time", "User", "Action", "Details"])
    with open(LOGS_FILE, mode='a', newline='') as file:
        writer = csv.writer(file); writer.writerow([timestamp, user, action, details])

def load_beds():
    global beds_status
    beds_status = ["Free"] * TOTAL_BEDS
    for p in all_patients:
        if p.status == "Admitted" and p.room.startswith("Bed-"):
            try:
                bed_num = int(p.room.split("-")[1]) - 1
                if 0 <= bed_num < TOTAL_BEDS: beds_status[bed_num] = p.name
            except: pass

def load_data():
    global all_patients, waiting_queue, all_doctors, all_logs
    all_patients = []; waiting_queue = MaxHeap(); all_doctors = []; all_logs = []

    if not os.path.exists(DOCTORS_FILE):
        with open(DOCTORS_FILE, 'w', newline='') as f: csv.writer(f).writerow(["Name", "Specialty", "Room", "Keywords"]); csv.writer(f).writerow(["Dr. Sarah", "Cardiology", "Room 101", "heart,attack"])
    with open(DOCTORS_FILE, 'r') as f:
        for row in csv.DictReader(f): all_doctors.append(Doctor(row["Name"], row["Specialty"], row["Room"], row["Keywords"]))

    if os.path.exists(PATIENTS_FILE):
        with open(PATIENTS_FILE, 'r') as f:
            for row in csv.DictReader(f):
                p = Patient(row["ID"], row["Name"], row["Age"], row["Disease"], row["Status"], row.get("Priority", "Normal"), row.get("Room", "-"), row.get("Severity", "Low"), row.get("Doctor", "-"), row.get("Time", "-"), row.get("EstDays", 1))
                all_patients.append(p)
                if p.status == "Waiting": waiting_queue.insert(p)

    # Load Logs (This was missing causing NameError)
    if os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'r') as f:
            for row in csv.DictReader(f): all_logs.append(Log(row["Time"], row["User"], row["Action"], row["Details"]))
    all_logs.reverse()

def load_logs():
    # Helper to refresh logs specifically
    global all_logs; all_logs = []
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'w', newline='') as f: csv.writer(f).writerow(["Time", "User", "Action", "Details"])
    with open(LOGS_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader: all_logs.append(Log(row["Time"], row["User"], row["Action"], row["Details"]))
    all_logs.reverse()

def save_patients():
    with open(PATIENTS_FILE, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(["ID", "Name", "Age", "Disease", "Status", "Priority", "Room", "Severity", "Doctor", "Time", "EstDays"])
        for p in all_patients: w.writerow([p.id, p.name, p.age, p.disease, p.status, p.priority, p.room, p.severity, p.doc, p.time, p.est_days])

def save_doctor(name, spec, room, keys):
    with open(DOCTORS_FILE, 'a', newline='') as f: csv.writer(f).writerow([name, spec, room, keys])
    log_activity("Hiring", f"Added {name}")

def smart_triage(disease, age):
    severity = "Low"; days = 1
    if any(x in disease.lower() for x in ['heart', 'stroke', 'trauma']): severity = "Critical"; days = 15
    elif any(x in disease.lower() for x in ['flu', 'fever']): severity = "Low"; days = 2
    elif any(x in disease.lower() for x in ['fracture', 'dengue']): severity = "Moderate"; days = 7
    return severity, days

def predict_influx():
    base = len(all_patients) if len(all_patients) > 0 else 10
    prediction = []
    for i in range(1, 6):
        val = int(base * random.uniform(0.7, 1.3)) + i
        prediction.append(val)
    return prediction

# ==========================================
#  ROUTES
# ==========================================
@app.route('/')
def dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    load_data(); load_beds()
    all_patients.sort(key=lambda x: x.id) 
    trend = [random.randint(5, 25) for _ in range(7)]
    return render_template('dashboard.html', 
                           patients=all_patients, doctors=all_doctors, 
                           beds=beds_status, 
                           queue_count=len(waiting_queue), 
                           active_count=sum(1 for p in all_patients if p.status != "Discharged"), 
                           trend_data=trend, forecast_data=predict_influx(),
                           user_role=session.get('role', 'staff'), 
                           msg=request.args.get('msg'))

@app.route('/add', methods=['POST'])
def add_patient():
    load_data()
    if any(p.id == int(request.form['id']) for p in all_patients): return redirect(url_for('dashboard', msg="error_duplicate"))
    
    severity, days = smart_triage(request.form['disease'], int(request.form['age']))
    priority = "Critical" if 'is_critical' in request.form or severity == "Critical" else "Normal"
    time = f"{random.randint(9,12)}:{random.choice(['00','30'])} AM"
    
    # FIXED: Safe Get to prevent KeyError
    assigned_doc = request.form.get('assigned_doctor', 'General Physician')

    new_p = Patient(request.form['id'], request.form['name'], request.form['age'], request.form['disease'], "Waiting", priority, "-", severity, assigned_doc, time, days)
    all_patients.append(new_p); save_patients()
    log_activity("Register", f"Added {new_p.name} (Priority: {new_p.priority_score})")
    return redirect(url_for('dashboard', msg="success_added"))

@app.route('/admit/<int:bed_id>')
def admit_to_bed(bed_id):
    load_data()
    target_patient = waiting_queue.extract_max()
    if target_patient:
        for p in all_patients:
            if p.id == target_patient.id: p.status = "Admitted"; p.room = f"Bed-{bed_id + 1}"; log_activity("Admit", f"Admitted {p.name} to Bed-{bed_id + 1}"); break
        save_patients(); return redirect(url_for('dashboard', msg="success_admitted"))
    else:
        return redirect(url_for('dashboard', msg="error_empty"))

@app.route('/admit')
def admit_auto():
    load_data(); load_beds()
    for i in range(TOTAL_BEDS):
        if beds_status[i] == "Free": return admit_to_bed(i)
    return redirect(url_for('dashboard', msg="error_full"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username']; p = request.form['password']
        if u == "admin" and p == "admin123": session['logged_in'] = True; session['user'] = "Admin"; session['role'] = "admin"; log_activity("Login", "Admin Access"); return redirect(url_for('dashboard'))
        elif u == "staff" and p == "staff123": session['logged_in'] = True; session['user'] = "Staff"; session['role'] = "staff"; log_activity("Login", "Staff Access"); return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/discharge/<int:p_id>')
def discharge_patient(p_id):
    if session.get('role') != 'admin': return redirect(url_for('dashboard', msg="error_denied"))
    load_data()
    for p in all_patients: 
        if p.id == p_id: p.status = "Discharged"; p.room = "-"; log_activity("Discharge", f"Discharged {p.id}"); break
    save_patients(); return redirect(url_for('dashboard'))

@app.route('/delete/<int:p_id>')
def delete_patient(p_id):
    if session.get('role') != 'admin': return redirect(url_for('dashboard', msg="error_denied"))
    load_data(); global all_patients
    all_patients = [p for p in all_patients if p.id != p_id]
    save_patients(); log_activity("Delete", f"Deleted ID {p_id}")
    return redirect(url_for('dashboard', msg="success_deleted"))

@app.route('/backup')
def backup():
    if session.get('role') != 'admin': return redirect(url_for('dashboard', msg="error_denied"))
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        if os.path.exists(PATIENTS_FILE): zf.write(PATIENTS_FILE)
        if os.path.exists(DOCTORS_FILE): zf.write(DOCTORS_FILE)
        if os.path.exists(LOGS_FILE): zf.write(LOGS_FILE)
    memory_file.seek(0); return send_file(memory_file, download_name="backup.zip", as_attachment=True)

@app.route('/bill/<int:p_id>')
def bill(p_id): load_data(); p = next((x for x in all_patients if x.id==p_id), None); return render_template('bill.html', p=p, total=2000+(p.est_days*2000), date=datetime.date.today()) if p else redirect(url_for('dashboard'))
@app.route('/idcard/<int:p_id>')
def id_card(p_id): load_data(); p = next((x for x in all_patients if x.id==p_id), None); return render_template('card.html', p=p) if p else redirect(url_for('dashboard'))
@app.route('/add_doctor', methods=['POST'])
def add_doctor(): save_doctor(request.form['doc_name'], request.form['doc_spec'], request.form['doc_room'], request.form['doc_keys']); return redirect(url_for('doctors'))
@app.route('/doctors')
def doctors(): load_data(); return render_template('doctors.html', doctors=all_doctors)
@app.route('/logs')
def logs(): 
    if session.get('role') != 'admin': return redirect(url_for('dashboard', msg="error_denied"))
    load_logs(); return render_template('logs.html', logs=all_logs)
@app.route('/about')
def about(): return render_template('about.html')

if __name__ == '__main__': app.run(debug=True)