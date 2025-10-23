import json
import os
from datetime import datetime

class Database:
    def __init__(self):
        self.courses_file = 'data/courses.json'
        self.exercises_file = 'data/exercises.json'
        self.progress_file = 'data/progress.json'
        self.documents_file = 'data/documents.json'
        self.submissions_file = 'data/submissions.json'
        self._init_files()
    
    def _init_files(self):
        """Khởi tạo các file JSON nếu chưa có"""
        files = [
            self.courses_file, 
            self.exercises_file, 
            self.progress_file, 
            self.documents_file,
            self.submissions_file
        ]
        for file in files:
            if not os.path.exists(file):
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump([], f)
    
    def _load_json(self, filename):
        """Load dữ liệu từ file JSON"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _save_json(self, filename, data):
        """Lưu dữ liệu vào file JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_all_courses(self):
        """Lấy tất cả khóa học"""
        return self._load_json(self.courses_file)
    
    def get_course_by_id(self, course_id):
        """Lấy khóa học theo ID"""
        courses = self.get_all_courses()
        return next((c for c in courses if c['id'] == course_id), None)
    
    def get_courses_by_teacher(self, teacher_id):
        """Lấy khóa học của giáo viên"""
        courses = self.get_all_courses()
        return [c for c in courses if c['teacher_id'] == teacher_id]
    
    def create_course(self, course_data, teacher_id):
        """Tạo khóa học mới"""
        courses = self.get_all_courses()
        course_id = f"course_{len(courses) + 1}"
        
        new_course = {
            'id': course_id,
            'teacher_id': teacher_id,
            'title': course_data['title'],
            'description': course_data.get('description', ''),
            'lessons': course_data.get('lessons', []),
            'created_at': datetime.now().isoformat()
        }
        
        courses.append(new_course)
        self._save_json(self.courses_file, courses)
        return course_id
    
    def update_course(self, course_id, course_data):
        """Cập nhật khóa học"""
        courses = self.get_all_courses()
        for i, course in enumerate(courses):
            if course['id'] == course_id:
                courses[i].update(course_data)
                courses[i]['updated_at'] = datetime.now().isoformat()
                self._save_json(self.courses_file, courses)
                return True
        return False
    
    def get_all_exercises(self):
        """Lấy tất cả bài tập"""
        return self._load_json(self.exercises_file)
    
    def save_exercise_submission(self, user_id, submission_data):
        """Lưu bài làm của học sinh"""
        submissions = self._load_json(self.submissions_file)
        
        submission = {
            'id': f"sub_{len(submissions) + 1}",
            'user_id': user_id,
            'course_id': submission_data.get('course_id'),
            'exercise_id': submission_data['exercise_id'],
            'answers': submission_data['answers'],
            'submitted_at': submission_data.get('submitted_at', datetime.now().isoformat())
        }
        
        submissions.append(submission)
        self._save_json(self.submissions_file, submissions)
        return submission['id']
    
    def get_student_progress(self, user_id):
        """Lấy tiến độ học của học sinh"""
        progress_list = self._load_json(self.progress_file)
        return [p for p in progress_list if p['user_id'] == user_id]
    
    def get_course_progress(self, user_id, course_id):
        """Lấy tiến độ của học sinh trong 1 khóa học"""
        progress_list = self._load_json(self.progress_file)
        return next((p for p in progress_list if p['user_id'] == user_id and p['course_id'] == course_id), None)
    
    def update_progress(self, user_id, course_id, lesson_id, completed, **kwargs):
        """Cập nhật tiến độ học"""
        progress_list = self._load_json(self.progress_file)
        
        timestamp = kwargs.get('timestamp', datetime.now().isoformat())
        
        progress = next((p for p in progress_list if p['user_id'] == user_id and p['course_id'] == course_id), None)
        
        if progress:
            if completed and lesson_id not in progress['completed_lessons']:
                progress['completed_lessons'].append(lesson_id)
            progress['last_updated'] = timestamp
        else:
            progress = {
                'user_id': user_id,
                'course_id': course_id,
                'completed_lessons': [lesson_id] if completed else [],
                'last_updated': timestamp
            }
            progress_list.append(progress)
        
        self._save_json(self.progress_file, progress_list)
        return True
    
    def get_all_documents(self):
        """Lấy tất cả tài liệu"""
        return self._load_json(self.documents_file)
    
    def add_document(self, doc_data):
        """Thêm tài liệu mới"""
        documents = self.get_all_documents()
        doc_id = f"doc_{len(documents) + 1}"
        
        url = doc_data.get('url') or doc_data.get('link', '')
        
        new_doc = {
            'id': doc_id,
            'title': doc_data['title'],
            'type': doc_data.get('type', 'document'),
            'url': url,
            'description': doc_data.get('description', ''),
            'created_at': datetime.now().isoformat()
        }
        
        documents.append(new_doc)
        self._save_json(self.documents_file, documents)
        return doc_id
    
    def get_all_submissions(self):
        """Lấy tất cả bài nộp"""
        return self._load_json(self.submissions_file)
    
    def get_submissions_by_course(self, course_id):
        """Lấy bài nộp theo khóa học"""
        submissions = self.get_all_submissions()
        return [s for s in submissions if s.get('course_id') == course_id]