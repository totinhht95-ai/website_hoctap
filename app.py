from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import os

from utils.auth import register_user, login_user, get_user_by_id
from utils.database import Database
from utils.gemini_api import chat_with_gemini
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.config['SESSION_COOKIE_SECURE'] = False  # Đổi thành True nếu dùng HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


db = Database()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập', 'warning')
            return redirect(url_for('login'))
        
        user = get_user_by_id(session['user_id'])
        if not user or user['role'] != 'teacher':
            flash('Chỉ giáo viên mới có quyền truy cập trang này', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập', 'warning')
            return redirect(url_for('login'))
        
        user = get_user_by_id(session['user_id'])
        if not user or user['role'] != 'student':
            flash('Chỉ học sinh mới có quyền truy cập trang này', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    
    total_courses = len(db.get_all_courses())
    total_documents = len(db.get_all_documents())
    
    return render_template('index.html', 
                         total_courses=total_courses,
                         total_documents=total_documents)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        email = request.form.get('email', '').strip()
        
        if not username or not password or not email:
            flash('Vui lòng điền đầy đủ thông tin', 'danger')
            return render_template('register.html')
        
        result = register_user(username, password, email, role='student')
        
        if result['success']:
            flash('Đăng ký thành công! Vui lòng đăng nhập', 'success')
            return redirect(url_for('login'))
        else:
            flash(result['message'], 'danger')
            return render_template('register.html')
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Vui lòng nhập tên đăng nhập và mật khẩu', 'danger')
            return render_template('login.html')
        
        result = login_user(username, password)
        
        if result['success']:
            session['user_id'] = result['user_id']
            session['username'] = result['username']
            session['role'] = result['role']
            
            flash(f'Chào mừng {result["username"]}!', 'success')
            
            if result['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash(result['message'], 'danger')
            return render_template('login.html')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    username = session.get('username', 'Người dùng')
    session.clear()
    flash(f'Tạm biệt {username}!', 'info')
    return redirect(url_for('index'))


@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    courses = db.get_all_courses()
    my_progress = db.get_student_progress(session['user_id'])
    
    enrolled_courses = []
    for progress in my_progress:
        course = db.get_course_by_id(progress['course_id'])
        if course:
            total_lessons = len(course.get('lessons', []))
            completed_lessons = len(progress.get('completed_lessons', []))
            percentage = (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0
            
            enrolled_courses.append({
                'course': course,
                'progress': progress,
                'percentage': round(percentage, 1)
            })
    
    return render_template('student_dashboard.html', 
                         courses=courses,
                         enrolled_courses=enrolled_courses,
                         username=session.get('username'))


@app.route('/teacher/dashboard')
@login_required
@teacher_required
def teacher_dashboard():
    my_courses = db.get_courses_by_teacher(session['user_id'])
    
    course_stats = []
    for course in my_courses:
        all_progress = db._load_json(db.progress_file)
        students_enrolled = len([p for p in all_progress if p['course_id'] == course['id']])
        
        course_stats.append({
            'course': course,
            'students_enrolled': students_enrolled,
            'total_lessons': len(course.get('lessons', []))
        })
    
    return render_template('teacher_dashboard.html',
                         courses=course_stats,
                         username=session.get('username'))


@app.route('/courses')
@login_required
def courses():
    all_courses = db.get_all_courses()
    
    courses_with_teacher = []
    for course in all_courses:
        teacher = get_user_by_id(course['teacher_id'])
        course['teacher_name'] = teacher['username'] if teacher else 'Unknown'
        courses_with_teacher.append(course)
    
    return render_template('courses.html', courses=courses_with_teacher)


@app.route('/course/<course_id>')
@login_required
def course_detail(course_id):
    course = db.get_course_by_id(course_id)
    
    if not course:
        flash('Khóa học không tồn tại', 'danger')
        return redirect(url_for('courses'))
    
    teacher = get_user_by_id(course['teacher_id'])
    course['teacher_name'] = teacher['username'] if teacher else 'Unknown'
    
    progress = db.get_course_progress(session['user_id'], course_id)
    completed_lessons = progress['completed_lessons'] if progress else []
    
    is_teacher = session.get('role') == 'teacher' and course['teacher_id'] == session['user_id']
    
    return render_template('course_detail.html', 
                         course=course,
                         completed_lessons=completed_lessons,
                         is_teacher=is_teacher)


@app.route('/teacher/create_course', methods=['GET', 'POST'])
@teacher_required
def create_course():
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if not data.get('title'):
                return jsonify({'success': False, 'message': 'Vui lòng nhập tên khóa học'})
            
            all_courses = db.get_all_courses()
            if any(c['title'].lower() == data['title'].lower() and c['teacher_id'] == session['user_id'] for c in all_courses):
                return jsonify({'success': False, 'message': 'Bạn đã có khóa học trùng tên này'})
            
            course_id = db.create_course(data, session['user_id'])
            
            return jsonify({'success': True, 'course_id': course_id, 'message': 'Tạo khóa học thành công'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('create_course.html')


@app.route('/teacher/edit_course/<course_id>', methods=['GET', 'POST'])
@teacher_required
def edit_course(course_id):
    course = db.get_course_by_id(course_id)
    
    if not course:
        flash('Khóa học không tồn tại', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    if course['teacher_id'] != session['user_id']:
        flash('Bạn không có quyền chỉnh sửa khóa học này', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            success = db.update_course(course_id, data)
            
            if success:
                return jsonify({'success': True, 'message': 'Cập nhật khóa học thành công'})
            else:
                return jsonify({'success': False, 'message': 'Cập nhật thất bại'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('create_course.html', course=course, edit_mode=True)


@app.route('/teacher/delete_course/<course_id>', methods=['POST'])
@teacher_required
def delete_course(course_id):
    course = db.get_course_by_id(course_id)
    
    if not course:
        return jsonify({'success': False, 'message': 'Khóa học không tồn tại'})
    
    if course['teacher_id'] != session['user_id']:
        return jsonify({'success': False, 'message': 'Bạn không có quyền xóa khóa học này'})
    
    courses = db.get_all_courses()
    courses = [c for c in courses if c['id'] != course_id]
    db._save_json(db.courses_file, courses)
    
    return jsonify({'success': True, 'message': 'Xóa khóa học thành công'})


@app.route('/exercises')
@login_required
def exercises():
    all_courses = db.get_all_courses()
    
    exercises_list = []
    for course in all_courses:
        for lesson in course.get('lessons', []):
            questions = lesson.get('questions', [])
            if questions:
                exercises_list.append({
                    'course_id': course['id'],
                    'course_title': course['title'],
                    'lesson_id': lesson['id'],
                    'lesson_title': lesson['title'],
                    'questions': questions
                })
    
    try:
        all_submissions = db._load_json(db.submissions_file) if hasattr(db, 'submissions_file') else []
    except:
        all_submissions = []
    
    my_submissions = [s for s in all_submissions if s.get('user_id') == session['user_id']]
    
    return render_template('exercises.html', 
                         exercises=exercises_list,
                         submissions=my_submissions)


@app.route('/submit_exercise', methods=['POST'])
@login_required
def submit_exercise():
    try:
        data = request.get_json()
        
        if not data.get('course_id') or not data.get('lesson_id') or not data.get('answers'):
            return jsonify({'success': False, 'message': 'Dữ liệu không đầy đủ'})
        
        submission_data = {
            'course_id': data['course_id'],
            'exercise_id': data['lesson_id'],
            'answers': data['answers'],
            'submitted_at': datetime.now().isoformat()
        }
        
        submission_id = db.save_exercise_submission(session['user_id'], submission_data)
        
        course = db.get_course_by_id(data['course_id'])
        if course:
            lesson = next((l for l in course.get('lessons', []) if l['id'] == data['lesson_id']), None)
            if lesson:
                questions = lesson.get('questions', [])
                correct = 0
                total = len(questions)
                
                for i, q in enumerate(questions):
                    user_answer = data['answers'].get(str(i), '').strip()
                    correct_answer = q.get('correct_answer', '').strip()
                    
                    if user_answer and correct_answer:
                        user_first_char = user_answer.split('.')[0].strip().upper()
                        correct_first_char = correct_answer.split('.')[0].strip().upper()
                        
                        if user_first_char == correct_first_char:
                            correct += 1
                
                score = round((correct / total * 100) if total > 0 else 0, 1)
                
                return jsonify({
                    'success': True,
                    'submission_id': submission_id,
                    'score': score,
                    'correct': correct,
                    'total': total,
                    'message': 'Nộp bài thành công'
                })
        
        return jsonify({'success': True, 'submission_id': submission_id, 'message': 'Nộp bài thành công'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


# CHỈNH SỬA: Route documents mới với filter theo lớp và loại tài liệu
@app.route('/documents')
@login_required
def documents():
    # Lấy các tham số lọc từ query string
    grade_filter = request.args.get('grade', 'all')  # 10, 11, 12, hoặc all
    type_filter = request.args.get('type', 'all')    # document, lecture, exam, hoặc all
    
    docs = db.get_all_documents()
    
    # Lọc theo lớp nếu có
    if grade_filter != 'all':
        docs = [d for d in docs if d.get('grade') == grade_filter]
    
    # Lọc theo loại tài liệu nếu có
    if type_filter != 'all':
        docs = [d for d in docs if d.get('doc_type') == type_filter]
    
    # Phân loại tài liệu theo lớp
    docs_by_grade = {
        '10': [d for d in docs if d.get('grade') == '10'],
        '11': [d for d in docs if d.get('grade') == '11'],
        '12': [d for d in docs if d.get('grade') == '12']
    }
    
    return render_template('documents.html',
                         docs_by_grade=docs_by_grade,
                         current_grade=grade_filter,
                         current_type=type_filter)


# CHỈNH SỬA: Route thêm tài liệu mới với các trường lớp và loại tài liệu
@app.route('/teacher/add_document', methods=['GET', 'POST'])
@teacher_required
def add_document():
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if not data.get('title') or not data.get('url'):
                return jsonify({'success': False, 'message': 'Vui lòng nhập đầy đủ thông tin'})
            
            # Thêm trường grade và doc_type vào dữ liệu
            if not data.get('grade'):
                return jsonify({'success': False, 'message': 'Vui lòng chọn lớp học'})
            
            if not data.get('doc_type'):
                return jsonify({'success': False, 'message': 'Vui lòng chọn loại tài liệu'})
            
            # Tự động xác định loại link (youtube, drive, other)
            if 'youtube.com' in data['url'] or 'youtu.be' in data['url']:
                data['link_type'] = 'youtube'
            elif 'drive.google.com' in data['url']:
                data['link_type'] = 'drive'
            else:
                data['link_type'] = data.get('link_type', 'other')
            
            doc_id = db.add_document(data)
            
            return jsonify({'success': True, 'doc_id': doc_id, 'message': 'Thêm tài liệu thành công'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    
    return render_template('add_document.html')


@app.route('/chatbot')
@login_required
def chatbot():
    return render_template('chatbot.html', username=session.get('username'))


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({'success': False, 'response': 'Vui lòng nhập tin nhắn'})
        
        response = chat_with_gemini(message)
        
        return jsonify({'success': True, 'response': response})
    
    except Exception as e:
        return jsonify({'success': False, 'response': f'Xin lỗi, có lỗi xảy ra: {str(e)}'})


@app.route('/update_progress', methods=['POST'])
@login_required
def update_progress():
    try:
        data = request.get_json()
        
        if not data.get('course_id') or not data.get('lesson_id'):
            return jsonify({'success': False, 'message': 'Dữ liệu không đầy đủ'})
        
        db.update_progress(
            session['user_id'],
            data['course_id'],
            data['lesson_id'],
            data.get('completed', True),
            timestamp=datetime.now().isoformat()
        )
        
        return jsonify({'success': True, 'message': 'Cập nhật tiến độ thành công'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})


@app.route('/teacher/students_progress')
@teacher_required
def students_progress():
    teacher_courses = db.get_courses_by_teacher(session['user_id'])
    teacher_course_ids = [c['id'] for c in teacher_courses]
    
    all_progress = db._load_json(db.progress_file)
    filtered_progress = [p for p in all_progress if p['course_id'] in teacher_course_ids]
    
    progress_with_details = []
    for prog in filtered_progress:
        student = get_user_by_id(prog['user_id'])
        course = db.get_course_by_id(prog['course_id'])
        
        if student and course:
            total_lessons = len(course.get('lessons', []))
            completed = len(prog.get('completed_lessons', []))
            percentage = round((completed / total_lessons * 100) if total_lessons > 0 else 0, 1)
            
            progress_with_details.append({
                'student_name': student['username'],
                'student_email': student.get('email', ''),
                'course_title': course['title'],
                'completed': completed,
                'total': total_lessons,
                'percentage': percentage,
                'last_updated': prog.get('last_updated', 'Chưa cập nhật')
            })
    
    return render_template('student_progress.html', progress=progress_with_details)


@app.route('/teacher/view_submissions')
@teacher_required
def view_submissions():
    teacher_courses = db.get_courses_by_teacher(session['user_id'])
    teacher_course_ids = [c['id'] for c in teacher_courses]
    
    try:
        all_submissions = db._load_json(db.submissions_file) if hasattr(db, 'submissions_file') else []
    except:
        all_submissions = []
    
    filtered_submissions = [s for s in all_submissions if s.get('course_id') in teacher_course_ids]
    
    submissions_with_details = []
    for sub in filtered_submissions:
        student = get_user_by_id(sub['user_id'])
        course = db.get_course_by_id(sub.get('course_id'))
        
        if student and course:
            submissions_with_details.append({
                'student_name': student['username'],
                'course_title': course['title'],
                'exercise_id': sub.get('exercise_id'),
                'answers': sub.get('answers', {}),
                'submitted_at': sub.get('submitted_at', 'Không rõ')
            })
    
    return render_template('view_submissions.html', submissions=submissions_with_details)


@app.route('/api/course/<course_id>')
@login_required
def api_get_course(course_id):
    course = db.get_course_by_id(course_id)
    if course:
        return jsonify({'success': True, 'course': course})
    return jsonify({'success': False, 'error': 'Course not found'}), 404


@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500



########################
# ===== THÊM VÀO FILE app.py =====

# IMPORT THÊM: Cần import json để đọc file JSON
# -*- coding: utf-8 -*-
# THÊM VÀO FILE app.py
@app.route('/tracnghiem/lam-bai/<grade>/<exam_id>')
@login_required
@student_required
def lam_bai_tracnghiem(grade, exam_id):
    """
    Hiển thị đề trắc nghiệm để học sinh làm bài
    ✅ Fix: Logic thời gian chặt chẽ, xử lý session an toàn
    """
    # 1. VALIDATE GRADE
    if grade not in ['10', '11', '12']:
        flash('Lớp không hợp lệ', 'danger')
        return redirect(url_for('tracnghiem'))
    
    json_file = f'data/lop{grade}.json'
    
    try:
        # 2. ĐỌC FILE VÀ TÌM ĐỀ THI
        with open(json_file, 'r', encoding='utf-8') as f:
            exams_data = json.load(f)
            exams = exams_data.get('exams', [])
            
            exam = next((e for e in exams if e['id'] == exam_id), None)
            
            if not exam:
                flash('Đề thi không tồn tại', 'danger')
                return redirect(url_for('tracnghiem'))
            
            # Lấy thời gian làm bài (mặc định 15 phút)
            time_limit = exam.get('time_limit', 15)
            
            # QUAN TRỌNG: Đảm bảo time_limit hợp lệ
            if not isinstance(time_limit, (int, float)) or time_limit <= 0:
                time_limit = 15
                print(f"Warning: Invalid time_limit in exam {exam_id}, using default 15 minutes")
            
            # 3. XỬ LÝ SESSION THỜI GIAN
            session_key = f'exam_start_{grade}_{exam_id}'
            reset_param = request.args.get('reset', 'no')
            
            # Đảm bảo session permanent để không bị mất
            if not session.permanent:
                session.permanent = True
                session.modified = True
            
            # 4. TÍNH TOÁN THỜI GIAN CÒN LẠI
            should_create_new_session = False
            remaining_time = time_limit * 60  # Mặc định
            
            # Trường hợp 1: Yêu cầu reset
            if reset_param == 'yes':
                should_create_new_session = True
                print(f"Reset session for exam {exam_id}")
            
            # Trường hợp 2: Chưa có session
            elif session_key not in session:
                should_create_new_session = True
                print(f"New session for exam {exam_id}")
            
            # Trường hợp 3: Có session - tính thời gian còn lại
            else:
                try:
                    start_time_str = session.get(session_key)
                    
                    # Validate start_time
                    if not start_time_str or not isinstance(start_time_str, str):
                        raise ValueError("Invalid start_time format")
                    
                    start_time = datetime.fromisoformat(start_time_str)
                    current_time = datetime.now()
                    
                    # Tính elapsed time
                    elapsed_seconds = (current_time - start_time).total_seconds()
                    
                    # CRITICAL: Validate elapsed_seconds
                    if elapsed_seconds < 0:
                        # Thời gian bắt đầu ở tương lai?! -> Reset
                        print(f"ERROR: Negative elapsed time for exam {exam_id}")
                        should_create_new_session = True
                    elif elapsed_seconds > (time_limit * 60 * 2):
                        # Quá thời gian gấp đôi -> Session cũ, reset
                        print(f"WARNING: Session too old for exam {exam_id}")
                        should_create_new_session = True
                    else:
                        # Tính remaining time
                        remaining_time = (time_limit * 60) - elapsed_seconds
                        
                        # CRITICAL CHECK: Nếu hết giờ
                        if remaining_time <= 0:
                            flash('⏰ Đã hết thời gian làm bài! Vui lòng làm lại từ đầu.', 'warning')
                            # Xóa session cũ
                            session.pop(session_key, None)
                            session.modified = True
                            return redirect(url_for('tracnghiem'))
                        
                        print(f"Exam {exam_id}: {int(remaining_time)}s remaining")
                
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    # Bất kỳ lỗi nào với session -> Tạo mới
                    print(f"Session error for exam {exam_id}: {e}")
                    should_create_new_session = True
            
            # 5. TẠO SESSION MỚI NẾU CẦN
            if should_create_new_session:
                current_time = datetime.now()
                session[session_key] = current_time.isoformat()
                session.permanent = True
                session.modified = True
                remaining_time = time_limit * 60
                print(f"Created new session for exam {exam_id}, expires in {time_limit} minutes")
            
            # 6. FINAL VALIDATION
            # Đảm bảo remaining_time luôn dương và hợp lệ
            remaining_time = max(1, min(remaining_time, time_limit * 60))
            remaining_time = int(remaining_time)  # Convert to integer
            
            # 7. LOG (cho debug)
            print(f"""
            ===== EXAM SESSION INFO =====
            Exam: {exam_id} | Grade: {grade}
            Time Limit: {time_limit} minutes
            Remaining: {remaining_time} seconds ({remaining_time//60}m {remaining_time%60}s)
            Session Key: {session_key}
            Session Permanent: {session.permanent}
            ============================
            """)
            
            # 8. RENDER TEMPLATE
            return render_template('baitap.html',
                                 exam=exam,
                                 grade=grade,
                                 time_limit=time_limit,
                                 remaining_time=remaining_time,
                                 username=session.get('username'))
    
    except FileNotFoundError:
        flash('⚠️ Không tìm thấy dữ liệu đề thi', 'danger')
        return redirect(url_for('tracnghiem'))
    
    except json.JSONDecodeError as e:
        flash('⚠️ Dữ liệu đề thi bị lỗi định dạng', 'danger')
        print(f"JSON decode error: {e}")
        return redirect(url_for('tracnghiem'))
    
    except Exception as e:
        flash(f'⚠️ Lỗi không xác định: {str(e)}', 'danger')
        print(f"Unexpected error in lam_bai_tracnghiem: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('tracnghiem'))


# ===== BONUS: THÊM ROUTE KIỂM TRA THỜI GIAN REAL-TIME =====
@app.route('/api/tracnghiem/check-time/<grade>/<exam_id>')
@login_required
@student_required
def api_check_exam_time(grade, exam_id):
    """
    API kiểm tra thời gian còn lại - GỌI TỪ JAVASCRIPT
    Trả về: remaining_time (seconds) hoặc is_expired=True
    """
    session_key = f'exam_start_{grade}_{exam_id}'
    
    # Kiểm tra session tồn tại
    if session_key not in session:
        return jsonify({
            'success': False,
            'message': 'Session không tồn tại',
            'is_expired': True,
            'remaining_time': 0
        })
    
    try:
        # Đọc thông tin đề thi
        json_file = f'data/lop{grade}.json'
        with open(json_file, 'r', encoding='utf-8') as f:
            exams_data = json.load(f)
            exams = exams_data.get('exams', [])
            exam = next((e for e in exams if e['id'] == exam_id), None)
            
            if not exam:
                return jsonify({
                    'success': False,
                    'message': 'Đề thi không tồn tại',
                    'is_expired': True,
                    'remaining_time': 0
                })
            
            time_limit = exam.get('time_limit', 15)
        
        # Tính thời gian còn lại
        start_time = datetime.fromisoformat(session[session_key])
        elapsed_seconds = (datetime.now() - start_time).total_seconds()
        remaining_seconds = (time_limit * 60) - elapsed_seconds
        
        # Validate
        if remaining_seconds <= 0:
            # Hết giờ - xóa session
            session.pop(session_key, None)
            session.modified = True
            
            return jsonify({
                'success': True,
                'remaining_time': 0,
                'is_expired': True,
                'message': 'Hết thời gian'
            })
        
        return jsonify({
            'success': True,
            'remaining_time': int(remaining_seconds),
            'is_expired': False,
            'time_limit_minutes': time_limit
        })
    
    except (ValueError, KeyError, TypeError) as e:
        print(f"Error in api_check_exam_time: {e}")
        return jsonify({
            'success': False,
            'message': f'Lỗi session: {str(e)}',
            'is_expired': True,
            'remaining_time': 0
        })
    
    except Exception as e:
        print(f"Unexpected error in api_check_exam_time: {e}")
        return jsonify({
            'success': False,
            'message': f'Lỗi: {str(e)}',
            'is_expired': True,
            'remaining_time': 0
        })


# ===== THÊM: VALIDATE THỜI GIAN KHI NỘP BÀI =====
@app.route('/tracnghiem')
@login_required
@student_required
def tracnghiem():
    """
    Trang chọn đề thi trắc nghiệm
    """
    print("========= DEBUG TRACNGHIEM =========")
    print(f"User ID: {session.get('user_id')}")
    print(f"Role: {session.get('role')}")
    print(f"Username: {session.get('username')}")
    print("====================================")
    
    try:
        all_exams = []
        
        # Đọc đề thi từ 3 khối lớp
        for grade in ['10', '11', '12']:
            json_file = f'data/lop{grade}.json'
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    exams_data = json.load(f)
                    exams = exams_data.get('exams', [])
                    
                    # Thêm thông tin grade vào mỗi exam
                    for exam in exams:
                        exam['grade'] = grade
                    
                    all_exams.extend(exams)
                    print(f"✓ Loaded {len(exams)} exams from grade {grade}")
            
            except FileNotFoundError:
                print(f"✗ File {json_file} không tồn tại")
                continue
            except json.JSONDecodeError:
                print(f"✗ File {json_file} bị lỗi định dạng")
                continue
        
        # Nhóm đề thi theo khối
        exams_by_grade = {
            '10': [e for e in all_exams if e['grade'] == '10'],
            '11': [e for e in all_exams if e['grade'] == '11'],
            '12': [e for e in all_exams if e['grade'] == '12']
        }
        
        print(f"Total exams: {len(all_exams)}")
        print(f"Grade 10: {len(exams_by_grade['10'])}")
        print(f"Grade 11: {len(exams_by_grade['11'])}")
        print(f"Grade 12: {len(exams_by_grade['12'])}")
        
        return render_template('tracnghiem.html', 
                             exams_by_grade=exams_by_grade,
                             username=session.get('username'))
    
    except Exception as e:
        print(f"ERROR in tracnghiem route: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Lỗi khi tải danh sách đề thi: {str(e)}', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/tracnghiem/nop-bai', methods=['POST'])
@login_required
@student_required
def nop_bai_tracnghiem():
    """
    Nộp bài - ✅ Thêm validate thời gian
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'Không nhận được dữ liệu'
            }), 400
        
        grade = data.get('grade')
        exam_id = data.get('exam_id')
        answers = data.get('answers', {})
        
        # Validate input
        if not grade or not exam_id:
            return jsonify({
                'success': False,
                'message': 'Thiếu thông tin đề thi'
            }), 400
        
        if grade not in ['10', '11', '12']:
            return jsonify({
                'success': False,
                'message': 'Lớp không hợp lệ'
            }), 400
        
        # ✅ KIỂM TRA THỜI GIAN CÒN LẠI
        session_key = f'exam_start_{grade}_{exam_id}'
        
        if session_key not in session:
            return jsonify({
                'success': False,
                'message': '⚠️ Session đã hết hạn. Vui lòng làm lại.'
            }), 403
        
        # Đọc file JSON
        json_file = f'data/lop{grade}.json'
        with open(json_file, 'r', encoding='utf-8') as f:
            exams_data = json.load(f)
            exams = exams_data.get('exams', [])
            exam = next((e for e in exams if e['id'] == exam_id), None)
            
            if not exam:
                return jsonify({
                    'success': False,
                    'message': 'Không tìm thấy đề thi'
                }), 404
            
            time_limit = exam.get('time_limit', 15)
            
            # ✅ VALIDATE: Kiểm tra có hết giờ không
            try:
                start_time = datetime.fromisoformat(session[session_key])
                elapsed_seconds = (datetime.now() - start_time).total_seconds()
                
                if elapsed_seconds > (time_limit * 60):
                    # Nộp muộn - không chấp nhận
                    session.pop(session_key, None)
                    session.modified = True
                    
                    return jsonify({
                        'success': False,
                        'message': '⏰ Đã hết thời gian làm bài! Không thể nộp.'
                    }), 403
            
            except (ValueError, KeyError):
                return jsonify({
                    'success': False,
                    'message': 'Session không hợp lệ'
                }), 403
            
            # Chấm điểm (code cũ của bạn)
            questions = exam.get('questions', [])
            total_questions = len(questions)
            correct_count = 0
            wrong_answers = []
            
            for question in questions:
                q_id = str(question['id'])
                correct_answer = question['correct_answer'].strip()
                user_answer = answers.get(q_id, '').strip()
                
                if user_answer == correct_answer:
                    correct_count += 1
                else:
                    wrong_answers.append({
                        'question_number': question['number'],
                        'question_text': question['question'],
                        'user_answer': user_answer if user_answer else 'Không trả lời',
                        'correct_answer': correct_answer,
                        'explanation': question.get('explanation', '')
                    })
            
            score = round((correct_count / total_questions) * 10, 2) if total_questions > 0 else 0
            
            # ✅ Xóa session sau khi nộp thành công
            session.pop(session_key, None)
            session.modified = True
            
            # Lưu kết quả
            result_data = {
                'user_id': session['user_id'],
                'username': session.get('username', 'Unknown'),
                'grade': grade,
                'exam_id': exam_id,
                'exam_title': exam.get('title', ''),
                'score': score,
                'correct_count': correct_count,
                'total_questions': total_questions,
                'submitted_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                'time_spent_seconds': int(elapsed_seconds)  # ✅ Lưu thời gian làm bài
            }
            
            try:
                results_file = 'data/exam_results.json'
                os.makedirs('data', exist_ok=True)
                
                try:
                    with open(results_file, 'r', encoding='utf-8') as f:
                        all_results = json.load(f)
                except FileNotFoundError:
                    all_results = []
                
                all_results.append(result_data)
                
                with open(results_file, 'w', encoding='utf-8') as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                
                print(f"✅ Saved result: User {session['user_id']}, Score: {score}")
            
            except Exception as e:
                print(f"❌ Error saving result: {e}")
            
            return jsonify({
                'success': True,
                'score': score,
                'correct_count': correct_count,
                'total_questions': total_questions,
                'wrong_answers': wrong_answers,
                'message': 'Nộp bài thành công'
            })
    
    except FileNotFoundError:
        return jsonify({
            'success': False,
            'message': 'Không tìm thấy file dữ liệu đề thi'
        }), 404
    
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'message': 'Dữ liệu đề thi bị lỗi'
        }), 500
    
    except Exception as e:
        print(f"ERROR in nop_bai_tracnghiem: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Lỗi server: {str(e)}'
        }), 500

@app.route('/tracnghiem/lich-su')
@login_required
@student_required
def lich_su_tracnghiem():
    """
    Hiển thị lịch sử làm bài trắc nghiệm của học sinh
    """
    try:
        user_id = session.get('user_id')
        
        # Đọc file kết quả
        results_file = 'data/exam_results.json'
        
        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                all_results = json.load(f)
        except FileNotFoundError:
            all_results = []
        except json.JSONDecodeError:
            print("ERROR: exam_results.json bị lỗi định dạng")
            all_results = []
        
        # Lọc kết quả của user hiện tại và sắp xếp theo thời gian mới nhất
        user_results = [r for r in all_results if r.get('user_id') == user_id]
        user_results.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
        
        print(f"User {user_id} có {len(user_results)} bài đã làm")
        
        return render_template('lichsu_tracnghiem.html', 
                             results=user_results,
                             username=session.get('username'))
    
    except Exception as e:
        print(f"ERROR in lich_su_tracnghiem: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Lỗi khi tải lịch sử: {str(e)}', 'danger')
        return redirect(url_for('tracnghiem'))


@app.route('/tracnghiem/reset/<grade>/<exam_id>')
@login_required
@student_required
def reset_exam_session(grade, exam_id):
    """
    Reset session để làm lại bài thi
    """
    session_key = f'exam_start_{grade}_{exam_id}'
    
    if session_key in session:
        session.pop(session_key)
        session.modified = True
        flash('Đã reset bài thi. Bạn có thể làm lại từ đầu!', 'success')
    
    return redirect(url_for('lam_bai_tracnghiem', grade=grade, exam_id=exam_id, reset='yes'))


@app.route('/tracnghiem/ket-qua/<grade>/<exam_id>')
@login_required
@student_required
def ket_qua_tracnghiem(grade, exam_id):
    """
    Hiển thị kết quả bài làm (lấy từ sessionStorage JavaScript)
    """
    try:
        user_id = session.get('user_id')
        
        # Đọc file kết quả để lấy kết quả mới nhất
        results_file = 'data/exam_results.json'
        
        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                all_results = json.load(f)
        except FileNotFoundError:
            flash('Không tìm thấy kết quả bài làm', 'warning')
            return redirect(url_for('tracnghiem'))
        
        # Tìm kết quả mới nhất của user cho đề thi này
        matching_results = [
            r for r in all_results 
            if r.get('user_id') == user_id 
            and r.get('grade') == grade 
            and r.get('exam_id') == exam_id
        ]
        
        if not matching_results:
            flash('Không tìm thấy kết quả bài làm', 'warning')
            return redirect(url_for('tracnghiem'))
        
        # Lấy kết quả mới nhất
        result = matching_results[-1]
        
        return render_template('ketqua.html', 
                             result=result,
                             username=session.get('username'))
    
    except Exception as e:
        print(f"ERROR in ket_qua_tracnghiem: {str(e)}")
        flash(f'Lỗi khi hiển thị kết quả: {str(e)}', 'danger')
        return redirect(url_for('tracnghiem'))
        ####################3
if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)