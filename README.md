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

### שני כלי סריקה: analyze_code ו־Bandit

ה־pen_tester חייב להריץ שני כלים לפני שהוא נותן תשובה: `analyze_code` (הניתוח שלנו) ו־[Bandit](https://bandit.readthedocs.io).
ממצא של שני הכלים באותה שורה ועם אותו CWE הוא ממצא אחד, עם שני המקורות.
לממצא שרק Bandit מצא אין טסט התקפה, ולכן ב־`review` הוא מקבל ניסיון תיקון אחד, והכרטיס שלו תמיד "צריך אותך"
(`partial proof: no attack test`). קובץ הדוגמה `samples/bandit_cases.py` מכיל חמישה ממצאים כאלה.

```
.venv\Scripts\python.exe main.py samples/bandit_cases.py
```

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

### בדיקת התיקונים (`--verify`)

עם `--verify` (שכולל גם את `--fix`), אחרי ה־developer רץ סוכן ה־tester על כל תיקון מוצע.
האפליקציה (לא המודל) מחילה את התיקון על עותק בתיקייה `.work/run-<id>/`, והקובץ המקורי לא נכתב לעולם.
ה־tester מריץ שתי בדיקות על העותק:
- `rescan` – סורק שוב עם שני הכלים: האם החולשה נסגרה, והאם התיקון הוסיף חולשה חדשה.
- `run_behavior_tests` – מריץ שני סוגי טסטים מ־`samples/behavior/`:
  - `test_<name>_works.py` – ההתנהגות הרגילה. עובר על המקור ועל תיקון טוב.
  - `test_<name>_attack.py` – ההתקפה עצמה. נכשל על המקור (מוכיח שיש חולשה) ועובר על תיקון טוב.
    כל טסט התקפה נושא בשמו את שם החוק, ורץ רק טסט ההתקפה של החוק שמתקנים.

הטסטים רצים בתהליך נפרד, עם timeout של 30 שניות ועם סביבה מצומצמת: רק `PATH`, `SYSTEMROOT`, `WINDIR`, `COMSPEC`,
`TEMP`/`TMP` (בתוך תיקיית הריצה), `SAMPLE_UNDER_TEST` ו־`PYTHONDONTWRITEBYTECODE`. אין שם מפתחות או טוקנים.

המודל בוחר `verdict`: `approve`, `retry` (עם feedback ל־developer) או `human`.
האפליקציה מאשרת `approve` רק אם החולשה נסגרה, אין ממצאים חדשים ושני סוגי הטסטים עברו. אחרת הריצה נגמרת
ב־`invalid_action` וה־verdict הופך ל־`human`. המודל יכול להחמיר, אף פעם לא להקל.
בסוף הריצה האפליקציה מוחקת את תיקיית הריצה שלה. עם `--keep-work` התיקייה נשארת.

```
.venv\Scripts\python.exe main.py samples/login.py --verify
.venv\Scripts\python.exe main.py samples/injection.py --verify --model llm --trace
```

הפלט כולל גם `verification_report`. קוד יציאה 2 גם אם ריצת ה־tester נכשלה.
עם `--model llm`, ה־tester משתמש ב־OpenRouter, ולכן צריך להוסיף ל־`.env` גם:

```
OPENROUTER_API_KEY=המפתח-שלכם
```

אפשר להוסיף `OPENROUTER_MODEL=<model id>` כדי לבחור מודל אחר (ברירת המחדל: `cohere/north-mini-code:free`).
בשכבה החינמית של OpenRouter יש בערך 50 בקשות ליום.

### ריצת הצוות (`review`) והחלה (`apply`)

`review` מריץ את שלושת הסוכנים כגרף של LangGraph (`orchestrator.py`). לכל ממצא `real` יש עד 3 ניסיונות:
אם ה־tester מחזיר `retry`, ה־developer מקבל את ה־feedback ומנסה שוב.

```
.venv\Scripts\python.exe main.py review samples/login.py
.venv\Scripts\python.exe main.py review samples/login.py --model llm --trace
```

התוצאה היא כרטיסי החלטה ב־`reports/<file>-<זמן>.json` וב־`.md` (התיקייה לא נכנסת ל־git).
כרטיסי `needs_you` מופיעים קודם, ואחריהם כרטיסי `ready`. כל כרטיס כולל:
- הבעיה, ותוצאת טסט ה־attack לפני ואחרי.
- ה־diff והבדיקות.
- הניסיונות שנכשלו, ומה כדאי לבדוק.

רק אדם מחיל תיקונים, ורק אחרי שקרא את הכרטיסים:

```
.venv\Scripts\python.exe main.py apply reports/login-20261027-120000.json --ids F1,F2
```

apply מסרב (קוד יציאה 3, עם סיבה) במקרים האלה:
- כרטיס שאינו `ready`.
- קובץ שהשתנה מאז ה־review.
- שינויים חופפים.
- עותק משולב שלא עובר את הבדיקות.

אם הכל עובר, הוא כותב את הקובץ, מדפיס את ה־diff ויוצא עם 0. הוא אף פעם לא עושה commit.

### מגבלות זמן

- `HTTP_TIMEOUT` (30 שניות) הוא גבול קשיח לבקשה שלמה למודל, גם אם השרת שולח בייטים לאט.
- `RUN_DEADLINE_SECONDS` (300 שניות, ו־`REVIEW_DEADLINE_SECONDS` = 600 ל־`review`) הוא גבול לכל הרצה של `main.py`.
- `MAX_REQUESTS_PER_RUN`: לכל היותר 20 בקשות ל־OpenRouter בהרצה אחת. כשהוא עובר, אף סוכן לא מתחיל צעד חדש,
  הפלט כולל `run_deadline` עם רשימת מה שלא נעשה, וקוד היציאה הוא 2.
- עם `--trace` כל צעד מודפס ל־stderr ברגע שהוא קורה (שורות שמתחילות ב־`[trace] `), והמסלול המלא מודפס בסוף.
- בהתחלה האפליקציה מוחקת תיקיות `run-*` ב־`.work/` שנשארו מהרצה שנעצרה ושגילן מעל שעה.

### ניסיונות חוזרים (retry)

אם קריאה למודל נכשלת ב־timeout או בסטטוס זמני (429, 500, 502, 503, 504), האפליקציה מנסה שוב עד פעמיים:
אחרי 2 שניות ואחרי 6 שניות. אם השרת שולח `Retry-After` בשניות, היא מחכה לפיו (עד 20 שניות).
שגיאות כמו 400/401/403/404 לא חוזרות על עצמן. ל־Gemini יש גם מרווח של 4 שניות לפחות בין בקשות
(`MIN_REQUEST_INTERVAL` ב־`config.py`). כל ניסיון חוזר נרשם ב־trace (מספר הניסיון והסטטוס בלבד).

הרצת הטסטים:

```
.venv\Scripts\python.exe -m pytest -q
```

הממצאים הצפויים לכל קובץ דוגמה מופיעים ב־`samples/EXPECTED.md`.
