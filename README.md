# DevSecOps Agent Team

Three AI agents that check Python code for security issues:
- Pen tester: finds weaknesses
- Developer: proposes a fix
- Tester: verifies that the fix works

Project for the AI Agents course.

## התקנה והרצה

יצירת סביבה וירטואלית והתקנת התלויות (Windows):

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

הרצת סוכן ה־pen_tester על קובץ:

```
.venv\Scripts\python.exe main.py samples/login.py
.venv\Scripts\python.exe main.py samples/login.py --trace
```

הדוח מודפס כ־JSON. עם `--trace` מודפס גם מסלול ההחלטות של הסוכן (ל־stderr).
קוד היציאה: 0 = אין ממצאים, 1 = יש ממצאים, 2 = שגיאת קלט.

הרצת הטסטים:

```
.venv\Scripts\python.exe -m pytest -q
```

הממצאים הצפויים לכל קובץ דוגמה מופיעים ב־`samples/EXPECTED.md`.
