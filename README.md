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
קוד היציאה: 0 = אין ממצאים אמיתיים, 1 = יש לפחות ממצא אמיתי אחד (`real`),
2 = שגיאה, או שהריצה לא הסתיימה ב־final.

### הרצה עם מודל אמיתי (Groq)

ברירת המחדל היא `--model scripted`, מודל מבוסס חוקים שלא צריך מפתח.
כדי להשתמש במודל אמיתי, צרו בתיקיית הפרויקט קובץ בשם `.env` עם השורה:

```
GROQ_API_KEY=המפתח-שלכם
```

אפשר להוסיף גם `GROQ_MODEL=<model id>` כדי לבחור מודל אחר (ברירת המחדל: `openai/gpt-oss-120b`).
הקובץ `.env` מופיע ב־`.gitignore`, ולכן לא ייכנס ל־git. לעולם אל תכתבו את המפתח בקוד.

```
.venv\Scripts\python.exe main.py samples/login.py --model llm
.venv\Scripts\python.exe main.py samples/login.py --model llm --trace
```

המודל נותן לכל ממצא `verdict` (`real` או `false_positive`) ונימוק קצר.
הסוכן בודק את התשובה: אם המודל משמיט ממצא, מוסיף ממצא חדש או מחזיר JSON לא תקין, הריצה נגמרת ב־`invalid_action`.
הטסטים לא קוראים ל־API האמיתי.

### הצעת תיקונים (`--fix`)

עם `--fix`, אחרי ה־pen_tester רץ גם סוכן ה־developer. הוא מציע תיקון קטן (diff) לכל ממצא `real`.
ממצאי `false_positive` לא נשלחים אליו. הסוכן לא משנה את הקובץ המקורי. כל הצעה היא diff נפרד מול הקובץ המקורי, ואדם מחליט מה להחיל.

```
.venv\Scripts\python.exe main.py samples/login.py --fix
.venv\Scripts\python.exe main.py samples/login.py --fix --model llm --trace
```

הפלט הוא `{"findings_report": ..., "fix_report": ...}`. קוד יציאה 2 גם אם ריצת ה־developer נכשלה.

עם `--model llm`, ה־developer משתמש ב־Gemini, ולכן צריך להוסיף ל־`.env` גם:

```
GEMINI_API_KEY=המפתח-שלכם
```

אפשר להוסיף `GEMINI_MODEL=<model id>` כדי לבחור מודל אחר (ברירת המחדל: `gemini-3.1-flash-lite`).

הרצת הטסטים:

```
.venv\Scripts\python.exe -m pytest -q
```

הממצאים הצפויים לכל קובץ דוגמה מופיעים ב־`samples/EXPECTED.md`.
