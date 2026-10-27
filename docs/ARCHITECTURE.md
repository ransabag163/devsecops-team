# ארכיטקטורה – DevSecOps Agent Team

המסמך מתאר את הקוד כפי שהוא עכשיו, לא תוכניות. יש לעדכן אותו בכל שלב (ראו `CLAUDE.md`).

שלושה סוכנים עובדים בתור: **pen_tester** מוצא חולשות, **developer** מציע תיקון קטן כ־diff,
**tester** בודק את התיקון על עותק. אדם מחליט מה להחיל. אף סוכן לא כותב לקובץ המקורי.

עיקרון מרכזי: **המודל בוחר, האפליקציה אוכפת.** המודל רק מחזיר פעולת JSON אחת בכל צעד
(`tool`, `final` או `clarify`). האפליקציה בודקת כל פעולה לפני שהיא רצה, וכל ריצה נגמרת באחד
הסטטוסים `final`, `clarify`, `budget_exhausted` או `invalid_action`.

## 1. ריצה אחת מלאה

```mermaid
flowchart TD
    FILE["קובץ Python<br/>למשל samples/login.py"]

    subgraph PT["🔴 pen_tester – Groq · openai/gpt-oss-120b · עד 4 צעדים"]
        PT_T["כלים מותרים: analyze_code"]
    end

    subgraph DEV["🔵 developer – Gemini · gemini-3.1-flash-lite · עד 5 צעדים לכל ממצא"]
        DEV_T["כלים מותרים: read_snippet, make_diff"]
    end

    COPY["⚙️ האפליקציה מחילה את ההצעה על עותק<br/>.work/run-ID/"]

    subgraph TST["🟢 tester – OpenRouter · cohere/north-mini-code:free · עד 4 צעדים לכל הצעה"]
        TST_T["כלים מותרים: rescan, run_behavior_tests"]
    end

    HUMAN["👤 אדם<br/>קורא את הדוחות ומחליט אם להחיל את ה־diff"]

    FILE --> PT
    PT -->|"FindingsReport<br/>verdict לכל ממצא"| DEV
    PT -.->|"false_positive לא נשלח"| HUMAN
    DEV -->|"FixReport<br/>proposed / skipped"| COPY
    DEV -.->|"skipped לא נבדק"| HUMAN
    COPY --> TST
    TST -->|"VerificationReport<br/>approve / retry / human"| HUMAN
```

- `main.py` בלי דגלים מריץ רק את pen_tester. `--fix` מוסיף את developer, ו־`--verify` (כולל `--fix`) מוסיף את tester.
- `--model scripted` (ברירת המחדל) מריץ מודלים מבוססי חוקים בלי API. `--model llm` משתמש בספקים שבתרשים.
- את המודל של כל ספק אפשר להחליף ב־`.env`: `GROQ_MODEL`, `GEMINI_MODEL`, `OPENROUTER_MODEL`.
- ההרשאות לכלים מוגדרות ב־`ALLOWLIST` שב־`tools/registry.py`.

## 2. תיקיות וייבואים

כל חץ אומר "מייבא את". רק ייבואים בתוך הפרויקט, בלי הספרייה הסטנדרטית.

```mermaid
flowchart LR
    subgraph ROOT["שורש הפרויקט"]
        main["main.py"]
        config["config.py"]
        state["state.py"]
        deadline["deadline.py"]
    end

    subgraph AGENTS["agents/"]
        base_agent["base_agent.py"]
        pen_tester["pen_tester.py"]
        developer["developer.py"]
        tester["tester.py"]
    end

    subgraph MODELS["models/"]
        mbase["base.py"]
        llm_adapter["llm_adapter.py"]
        llm_common["llm_common.py"]
        llm_pen["llm_pen_tester.py"]
        llm_dev["llm_developer.py"]
        llm_tst["llm_tester.py"]
        scripted["scripted.py"]
    end

    subgraph TOOLS["tools/"]
        registry["registry.py"]
        analyze["analyze_code.py"]
        patch["patch_tools.py"]
        verify["verify_tools.py"]
        workspace["workspace.py"]
    end

    main --> config & deadline & pen_tester & developer & tester
    main --> llm_pen & llm_dev & llm_tst & scripted & workspace

    base_agent --> config & llm_adapter & registry
    pen_tester --> base_agent & state & config
    developer --> base_agent & state & registry & config
    tester --> base_agent & state & verify & workspace & config

    llm_pen & llm_dev & llm_tst --> llm_adapter & llm_common & config
    llm_common --> mbase
    scripted --> mbase & verify
    llm_adapter --> config

    registry --> analyze & patch & verify
    verify --> analyze & workspace & config
    workspace --> patch & config
    patch --> config
    analyze --> config
```

בתוך `samples/behavior/`, קובצי הטסט מייבאים את `behavior_helpers.py`, ו־`conftest.py` נותן להם fixtures.
הם לא מייבאים אף מודול של הפרויקט: הם טוענים את הקוד הנבדק מהנתיב שב־`SAMPLE_UNDER_TEST`.

## 3. כל הקבצים

הטבלה לא כוללת את `.venv`, `.work`, `__pycache__`, `.claude` ואת `.env`, שלא נמצא ב־git.

| קובץ | מה הוא עושה | בעלים |
|---|---|---|
| `main.py` | נקודת הכניסה: מריץ את הסוכנים לפי הדגלים, מדפיס את הדוחות ומחזיר קוד יציאה. | ⚙️ |
| `config.py` | כל ההגדרות: ספקים, מגבלות צעדים וזמן, תיקיות, וטעינת `.env` בלי להדפיס אותו. | ⚙️ |
| `state.py` | צורות הנתונים שהסוכנים מחזירים (ממצא, דוח, הצעה, אימות), עם בדיקת סטטוסים. | ⚙️ |
| `deadline.py` | מגבלת זמן אחת לכל ריצה של `main.py`, שכל הסוכנים והלקוח בודקים. | ⚙️ |
| `agents/__init__.py` | קובץ ריק שהופך את `agents/` לחבילה. | ⚙️ |
| `agents/base_agent.py` | לולאת הסוכן: שואל את המודל, מריץ כלים רק דרך ה־registry, ומסיים בסטטוס אחד. | ⚙️ |
| `agents/pen_tester.py` | בודק שהמודל נתן verdict לכל ממצא של הכלי, בלי להוסיף, להשמיט או לשכפל. | 🔴 |
| `agents/developer.py` | מריץ ריצה לכל ממצא `real`, בודק את ההצעה ובונה את ה־diff מחדש בעצמו. | 🔵 |
| `agents/tester.py` | מכין עותק לכל הצעה, מריץ את המודל ומאשר approve רק כשכל הבדיקות עברו. | 🟢 |
| `models/__init__.py` | קובץ ריק שהופך את `models/` לחבילה. | ⚙️ |
| `models/base.py` | המחלקה הבסיסית של מודל החלטות: `decide`, `last_retries`, `set_deadline`. | ⚙️ |
| `models/llm_adapter.py` | לקוח HTTP לממשקי צ'אט בסגנון OpenAI: timeout קשיח, retry, מרווח בין בקשות ושגיאות בלי המפתח. | ⚙️ |
| `models/llm_common.py` | קוד משותף לשלושת מודלי ה־LLM: בניית ההודעות, פענוח ה־JSON ומחלקת הבסיס. | ⚙️ |
| `models/llm_pen_tester.py` | ה־prompt של pen_tester והמודל שמדבר עם Groq. | 🔴 |
| `models/llm_developer.py` | ה־prompt של developer והמודל שמדבר עם Gemini. | 🔵 |
| `models/llm_tester.py` | ה־prompt של tester והמודל שמדבר עם OpenRouter. | 🟢 |
| `models/scripted.py` | שלושה מודלים מבוססי חוקים, בלי API, אחד לכל סוכן. | ⚙️ |
| `tools/__init__.py` | קובץ ריק שהופך את `tools/` לחבילה. | ⚙️ |
| `tools/registry.py` | הדרך היחידה להריץ כלי: allowlist לכל סוכן, טיפוסים מדויקים ונתיבים בתוך הפרויקט. | ⚙️ |
| `tools/analyze_code.py` | ניתוח סטטי עם `ast` לשלושה חוקים: CWE-89, CWE-798 ו־CWE-78. tester משתמש בו גם ב־`rescan`. | 🔴 |
| `tools/patch_tools.py` | `read_snippet` ו־`make_diff`, שעובדים על עותק בזיכרון. `apply_change` משותף גם ליצירת העותקים. | 🔵 |
| `tools/verify_tools.py` | `rescan`, `run_behavior_tests`, ואיסוף תוצאות הבדיקות מתוך תוצאות הכלים. | 🟢 |
| `tools/workspace.py` | יוצר ומוחק עותקים ב־`.work/run-<id>/`, כולל ניקוי תיקיות ישנות, עם בדיקת נתיב. | 🟢 |
| `samples/login.py` | קובץ דוגמה עם שלוש חולשות ידועות. | 🧪 |
| `samples/injection.py` | קובץ דוגמה עם shell injection והערה שמנסה לשכנע את המודל להתעלם. | 🧪 |
| `samples/clean.py` | קובץ דוגמה בלי חולשות. | 🧪 |
| `samples/notes.txt` | קובץ שאינו Python, לבדיקת השגיאה `unsupported_language`. | 🧪 |
| `samples/EXPECTED.md` | הממצאים הצפויים לכל קובץ דוגמה. | 🧪 |
| `samples/behavior/conftest.py` | טוען את הקוד הנבדק ומחליף כל דרך להריץ תהליך ב־recorder. | 🧪 |
| `samples/behavior/behavior_helpers.py` | עזרים שבודקים אם פקודה שנרשמה עוברת דרך shell, ומה המילים שלה. | 🧪 |
| `samples/behavior/test_login_works.py` | ההתנהגות הרגילה של login.py, שצריכה לעבור על המקור ועל תיקון טוב. | 🧪 |
| `samples/behavior/test_login_attack.py` | שלוש ההתקפות על login.py, אחת לכל חוק: נכשלות על המקור ועוברות על תיקון טוב. | 🧪 |
| `samples/behavior/test_injection_works.py` | ההתנהגות הרגילה של injection.py. | 🧪 |
| `samples/behavior/test_injection_attack.py` | ההתקפה על injection.py. | 🧪 |
| `tests/conftest.py` | חוסם קריאות API אמיתיות, המתנה אמיתית, ושימוש ב־`.work` האמיתי בכל הטסטים. | 🧪 |
| `tests/test_agent.py` | טסטים ללולאת הסוכן ולסטטוסים. | 🧪 |
| `tests/test_analyze_code.py` | טסטים לחוקי הניתוח הסטטי. | 🧪 |
| `tests/test_behavior_samples.py` | מוכיח ש־works עובר ו־attack נכשל על המקור, ושניהם עוברים על תיקון טוב. | 🧪 |
| `tests/test_config.py` | טסטים לטעינת `.env` ולהגדרות. | 🧪 |
| `tests/test_deadline.py` | טסטים למגבלת הזמן של הריצה, עם שעון מזויף. | 🧪 |
| `tests/test_developer.py` | טסטים לאכיפה של developer. | 🧪 |
| `tests/test_llm_adapter.py` | טסטים ללקוח ה־HTTP: retry, מרווח, timeout קשיח ושגיאות. | 🧪 |
| `tests/test_llm_developer.py` | טסטים למודל ה־LLM של developer, עם לקוח מזויף. | 🧪 |
| `tests/test_llm_pen_tester.py` | טסטים למודל ה־LLM של pen_tester, עם לקוח מזויף. | 🧪 |
| `tests/test_main.py` | טסטים לשורת הפקודה: דגלים, קודי יציאה, trace, ומפתחות שלא מופיעים בפלט. | 🧪 |
| `tests/test_models.py` | טסטים למודל מבוסס החוקים של pen_tester. | 🧪 |
| `tests/test_patch_tools.py` | טסטים ל־`read_snippet` ול־`make_diff`, כולל hash של הקובץ המקורי. | 🧪 |
| `tests/test_registry.py` | טסטים ל־allowlist, לטיפוסים ולנתיבים. | 🧪 |
| `tests/test_state.py` | טסטים לצורות הנתונים. | 🧪 |
| `tests/test_tester.py` | טסטים לאכיפה של tester: approve חסום, retry בלי feedback, ותיקיות ריצה. | 🧪 |
| `tests/test_tester_models.py` | טסטים למודלים של tester ולאיסוף הבדיקות. | 🧪 |
| `tests/test_verify_tools.py` | טסטים לעותקים, ל־`rescan`, ל־`run_behavior_tests`, לסביבה ול־timeout. | 🧪 |
| `pytest.ini` | מגדיר ש־pytest יריץ רק את `tests/` ויוכל לייבא מודולים משורש הפרויקט. | ⚙️ |
| `requirements.txt` | התלות היחידה: `pytest`. | ⚙️ |
| `.gitignore` | מונע מ־git לשמור את `.env`, ‏`.venv`, ‏`.work/`, ‏`.idea/` ו־`.claude/tmp/`. | ⚙️ |
| `README.md` | הוראות התקנה והרצה בעברית. | ⚙️ |
| `CLAUDE.md` | הכללים של הפרויקט ל־Claude. | ⚙️ |
| `docs/ARCHITECTURE.md` | המסמך הזה. | ⚙️ |

## 4. איך ריצה אחת עובדת

הפקודה: `main.py samples/login.py --verify --model llm --trace`

1. **התחלה.** `main.py` מפעיל שעון של 300 שניות לכל הריצה, ומוחק מ־`.work/` תיקיות `run-*` שגילן מעל שעה.
2. **pen_tester, צעד 1.** המודל (Groq) מבקש את הכלי `analyze_code`. ה־registry בודק שהכלי מותר ל־pen_tester ושהנתיב בתוך הפרויקט, ומריץ אותו.
   הכלי מוצא שלושה ממצאים: סיסמה בקוד (שורה 5), SQL שנבנה עם `+` (שורה 10), ו־`shell=True` עם קלט (שורה 18).
3. **pen_tester, צעד 2.** המודל מחזיר `final` עם `real` לכל ממצא ונימוק. האפליקציה בודקת שאף ממצא לא נוסף, לא הושמט ולא שוכפל.
   את ה־CWE ואת ה־evidence היא לוקחת מהכלי ולא מהמודל. התוצאה היא F1, F2 ו־F3.
4. **developer, לכל ממצא בנפרד (F1, F2, F3).** לכל ממצא יש ריצה חדשה של עד 5 צעדים:
   - המודל (Gemini) קורא את הקוד עם `read_snippet`.
   - הוא מנסה שינוי עם `make_diff`, שעובד על עותק בזיכרון ובודק שהקוד עדיין עובר `ast.parse`.
   - הוא מחזיר `final` עם הצעה.
   - האפליקציה בודקת שההצעה שייכת לממצא הנכון ושהשינוי במרחק של עד 10 שורות ממנו, ובונה את ה־diff מחדש בעצמה.
   - בריצה האמיתית: F1 עבר למשתנה סביבה, F2 לשאילתה עם `?`, ו־F3 לרשימת ארגומנטים בלי shell.
5. **tester, לכל הצעה בנפרד.**
   - האפליקציה (לא המודל) מחילה את ההצעה על עותק בתיקייה חדשה, `.work/run-<id>/`.
   - המודל (OpenRouter) מבקש את `rescan`, שסורק את העותק: האם החולשה נסגרה, והאם נוספה חולשה חדשה.
   - המודל מבקש את `run_behavior_tests`. הכלי מריץ את `test_login_works.py` ואת טסט ה־attack של החוק הנוכחי בלבד.
     הוא עושה זאת בתהליך נפרד, עם timeout של 30 שניות ובלי מפתחות בסביבה.
   - המודל מחזיר `approve`. האפליקציה בודקת בתוצאות הכלים שהכל באמת עבר, ורק אז מאשרת.
   - בסוף האפליקציה מוחקת את תיקיית הריצה.
6. **פלט.** stdout מכיל `findings_report`, `fix_report` ו־`verification_report`. עם `--trace` כל צעד מודפס ל־stderr ברגע שהוא קורה, והמסלול המלא מודפס בסוף.
   קוד היציאה הוא 1, כי יש ממצאים אמיתיים. בריצה האמיתית זה לקח 141 שניות, ושלושת התיקונים אושרו.
7. **אדם.** הקובץ `samples/login.py` לא השתנה. האדם קורא את ה־diff ואת האימות, ומחליט אם להחיל.

## 5. מה האפליקציה אוכפת

הכללים האלה נמצאים בקוד, לא ב־prompt, ולכן הם חלים גם כשהמודל לא מציית.

- **allowlist:** כל סוכן יכול להריץ רק את הכלים שלו. כלי אחר נחסם עם `tool_not_allowed`, וכלי לא מוכר עם `unknown_tool`.
- **ארגומנטים:** בדיוק הארגומנטים הצפויים ובטיפוס המדויק (`"5"` או `True` במקום מספר נחסמים). כל נתיב חייב להיות בתוך הפרויקט.
- **מספר צעדים:** pen_tester עד 4, developer עד 5 לכל ממצא, tester עד 4 לכל הצעה. אחר כך הסטטוס הוא `budget_exhausted`.
- **pen_tester:**
  - אין `final` לפני שהקובץ נותח.
  - אין הוספה, השמטה או שכפול של ממצאים.
  - ה־verdict חייב להיות `real` או `false_positive`, ועם נימוק לא ריק.
  - ה־CWE וה־evidence נלקחים מהכלי, לא מהמודל.
- **developer:**
  - רק ממצאי `real` נשלחים אליו.
  - ההצעה חייבת להיות לממצא הנוכחי, בסטטוס `proposed` או `skipped`, ו־`skipped` חייב הסבר.
  - השינוי חייב להיות עד 10 שורות מהממצא, עד 15 שורות מקוריות ו־30 חדשות, והקוד חייב לעבור `ast.parse`.
  - ה־diff נבנה מחדש על ידי האפליקציה. diff שהמודל כתב לא נמצא בשימוש.
- **tester:**
  - `approve` רק אם `closed` הוא true, אין `new_findings`, ו־works ו־attack שניהם `passed`, לפי תוצאות הכלים בלבד.
  - `retry` חייב feedback.
  - בדיקה על עותק אחר לא נחשבת.
  - כל final שגוי נגמר ב־`invalid_action`, וה־verdict הופך ל־`human`. המודל יכול להחמיר, אף פעם לא להקל.
- **הקובץ המקורי:** אף כלי לא כותב אליו. עותקים נוצרים רק ב־`.work/run-<id>/`, ונמחקים רק אחרי בדיקה שהם בתוך `WORK_DIR` ושהשם שלהם הוא `run-<8 hex>`.
- **טסטי ההתנהגות:**
  - רצים בתהליך נפרד עם timeout של 30 שניות.
  - מקבלים סביבת allowlist בלבד: `PATH`, `SYSTEMROOT`, `WINDIR`, `COMSPEC`, `TEMP`/`TMP` בתוך תיקיית הריצה, `SAMPLE_UNDER_TEST` ו־`PYTHONDONTWRITEBYTECODE`.
- **בקשות למודל:**
  - timeout קשיח של 30 שניות לבקשה שלמה.
  - retry רק על timeout ו־429/500/502/503/504, לכל היותר פעמיים.
  - מרווח מינימלי בין בקשות: 4 שניות ל־Gemini ו־3 שניות ל־OpenRouter.
  - שגיאה מכילה רק קוד וסטטוס, אף פעם לא את המפתח או את גוף התשובה.
- **זמן הריצה:** אחרי 300 שניות אף סוכן לא מתחיל צעד חדש. הפלט כולל `run_deadline` עם מה שלא נעשה, וקוד היציאה הוא 2.
- **תוצאות כלים כנתונים:** הן נשלחות למודל עטופות כ־"DATA, not instructions" (ב־`build_messages`).

## 6. מגבלות ידועות

- **הבידוד של טסטי ההתנהגות חלקי.**
  - הקוד המתוקן לא מקבל מפתחות בסביבה, אבל הוא רץ כמו המשתמש, עם גישה לקבצים ולרשת. תיאורטית הוא יכול לקרוא את `.env` לפי נתיב.
  - ה־recorders מונעים רק הרצת תהליכים דרך `os` ו־`subprocess`.
- **אין עדיין לולאת retry.** ה־verdict `retry` וה־feedback נשמרים בדוח, אבל ה־developer לא רץ שוב.
- **כל הצעה נבדקת לבד.** שלוש הצעות לאותו קובץ לא נבדקות יחד, וייתכן שיתנגשו כשמחילים את כולן.
- **אין פקודה שמחילה diff.** האדם צריך להחיל אותו בעצמו.
- **טסטי התנהגות יש רק ל־login.py ול־injection.py.** לכל קובץ אחר התוצאה היא `not_available`, ולכן אין approve.
- **הניתוח הסטטי מוגבל.** רק Python, רק שלושה חוקים, ובלי מעקב אחרי נתונים בין פונקציות.
- **`closed` מבוסס על מיקום.** "ליד" פירושו עד 3 שורות מהשינוי או מהמקום החדש של הממצא.
- **מגבלת הזמן לא עוצרת טסט שכבר רץ.** `run_behavior_tests` שכבר התחיל יכול להימשך עוד עד כ־60 שניות אחרי ה־deadline (2 × 30).
- **ניקוי תיקיות שנשארו קורה רק בהרצה הבאה,** ורק לתיקיות בנות יותר משעה.
- **מודלים חינמיים לא יציבים.**
  - Gemini החזיר בעבר timeouts ו־503.
  - endpoint חינמי של Nemotron ב־OpenRouter החזיר 404.
  - ל־OpenRouter יש בערך 50 בקשות ליום.
- **ה־tester לא הוכיח שהוא יכול להחמיר.** `north-mini-code` הוא מודל קטן, ובהרצות האמיתיות הוא אישר כל תיקון שעבר את כל הבדיקות. ההגנה האמיתית היא האכיפה של האפליקציה.
- **ה־developer המבוסס על חוקים מוגבל.** הוא מתקן רק `hardcoded_secret`, ומחזיר `skipped` לשאר.
