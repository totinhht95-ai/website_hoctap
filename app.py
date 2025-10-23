from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import os
from datetime import datetime
from utils.auth import register_user, login_user, get_user_by_id
from utils.database import Database
from utils.gemini_api import chat_with_gemini

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

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
    
    # SỬA LẠI: Lấy submissions từ file JSON thay vì gọi method không tồn tại
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
                
                # DEBUG LOG
                print("\n" + "="*50)
                print(f"DEBUG - Total questions: {total}")
                print(f"DEBUG - Total answers received: {len(data['answers'])}")
                print("="*50 + "\n")
                
                for i, q in enumerate(questions):
                    user_answer = data['answers'].get(str(i), '').strip()
                    correct_answer = q.get('correct_answer', '').strip()
                    
                    # DEBUG LOG CHO TUNG CAU
                    print(f"Cau {i+1}:")
                    print(f"  Question: {q.get('question', '')[:50]}...")
                    print(f"  User answer RAW: '{user_answer}'")
                    print(f"  Correct answer: '{correct_answer}'")
                    
                    if user_answer and correct_answer:
                        user_first_char = user_answer.split('.')[0].strip().upper()
                        correct_first_char = correct_answer.split('.')[0].strip().upper()
                        
                        print(f"  User char: '{user_first_char}'")
                        print(f"  Correct char: '{correct_first_char}'")
                        print(f"  Match: {user_first_char == correct_first_char}")
                        
                        if user_first_char == correct_first_char:
                            correct += 1
                            print(f"  [DUNG]")
                        else:
                            print(f"  [SAI]")
                    else:
                        print(f"  [THIEU DU LIEU]")
                    print()
                
                print("="*50)
                print(f"KET QUA CUOI: {correct}/{total}")
                print("="*50 + "\n")
                
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
        print(f"LOI: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})

@app.route('/documents')
@login_required
def documents():
    docs = db.get_all_documents()
    
    youtube_docs = [d for d in docs if 'youtube.com' in d['url'] or 'youtu.be' in d['url']]
    drive_docs = [d for d in docs if 'drive.google.com' in d['url']]
    other_docs = [d for d in docs if d not in youtube_docs and d not in drive_docs]
    
    return render_template('documents.html',
                         youtube_docs=youtube_docs,
                         drive_docs=drive_docs,
                         other_docs=other_docs)


@app.route('/teacher/add_document', methods=['GET', 'POST'])
@teacher_required
def add_document():
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if not data.get('title') or not data.get('url'):
                return jsonify({'success': False, 'message': 'Vui lòng nhập đầy đủ thông tin'})
            
            if 'youtube.com' in data['url'] or 'youtu.be' in data['url']:
                data['type'] = 'youtube'
            elif 'drive.google.com' in data['url']:
                data['type'] = 'drive'
            else:
                data['type'] = data.get('type', 'other')
            
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
    
    # SỬA LẠI: Lấy submissions từ file JSON
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


if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)