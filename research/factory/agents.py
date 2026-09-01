#!/usr/bin/env python3
"""
Реестр автономной системы: конвейер из шагов, часть которых ведёт
модель, а часть — код.

Почему отдельным модулем со стандартной библиотекой и без единого
импорта: этот реестр читает ВЕБ-СЕРВЕР (страница `/agents-page`), а
позже будет читать запускалка ролей — она собирает промпт агента из
той же записи, которой страница объясняет владельцу, что этот агент
делает. Две таблицы, решающие одно, однажды разойдутся: страница
описывала бы одну систему, а работала бы другая. Этим уже кончались
`nulls.py` в F3, загрузчик funding и список книг в восьми местах.

Два языка лежат в ОДНОЙ записи по правилу справочника: разъехавшись,
переводы стали бы двумя разными утверждениями об архитектуре, и
оспорить владелец мог бы только одно.

Чего этот файл НЕ утверждает: что система построена. Построенность
каждого шага решается СУЩЕСТВОВАНИЕМ файла из поля `proof`, и считает
её читатель, а не запись здесь. Иначе реестр рассказывал бы о системе,
которой нет, и выглядел бы при этом исправным — тот же класс отказа,
что молчаливый ноль на месте пропуска.

Агент здесь — НЕ живая сессия. Это рецепт запуска: промпт роли, права,
что прочитать, что оставить на диске. Сессия рождается на вызов и
умирает; между вызовами памяти нет, и разговаривают роли только через
файлы в git. Отсюда все правила ниже: состояние на диске, шаги
повторяемы без вреда, упавший прогон обязан кричать.
"""

# Поля, обязательные на обоих языках. Приписать шаг и забыть перевод —
# молчаливый отказ: страница показала бы английский абзац вперемешку с
# русскими и выглядела бы исправной.
BILINGUAL = ("title", "plain", "reads", "writes", "forbid", "doubt",
             "why", "cadence")

# Конвейер в ПОРЯДКЕ исполнения. `kind`: "role" — шаг ведёт модель,
# "mech" — шаг механический, кода достаточно.
#
# Разделение существенно и стоит первым: механический шаг нельзя
# уговорить. Отбор публикации, объявление в журнал, вылет и счёт
# знаменателя — механические намеренно, потому что именно там живёт
# соблазн, который в этом проекте уже стоил месяца работы (ошибка R5).
PIPELINE = [
    {
        "key": "runner", "kind": "mech", "model": "нет",
        "title": "scheduler",
        "title_ru": "запускалка",
        "cadence": "by the clock",
        "cadence_ru": "по расписанию",
        "plain": "Wakes each role at its own cadence, one writer at a "
                 "time, and leaves a line saying it ran.",
        "plain_ru": "Будит каждую роль в своё время, писатель в "
                    "репозиторий один за раз, и оставляет строку о "
                    "том, что прогон был.",
        "reads": "the schedule and the lock",
        "reads_ru": "расписание и замок",
        "writes": "a run line per wake-up",
        "writes_ru": "строку прогона на каждое пробуждение",
        "forbid": "never runs two writers at once",
        "forbid_ru": "никогда не пускает двух писателей разом",
        "doubt": "a run that dies leaves its cause; silence is an "
                 "alarm on this page, not a quiet day",
        "doubt_ru": "упавший прогон оставляет причину; тишина — "
                    "тревога на этой странице, а не спокойный день",
        "why": "A silent cron is indistinguishable from «nothing "
               "to propose today». The queue already refused "
               "concurrent publishing with «tree diverged».",
        "why_ru": "Молчащий крон неотличим от «сегодня нечего было "
                  "предлагать». Очередь заданий уже отказывала при "
                  "конкурентной публикации: «дерево разошлось».",
        "proof": "tools/agents_run.sh",
    },
    {
        "key": "brief", "kind": "role", "model": "дешёвая",
        "title": "keeper and briefer",
        "title_ru": "сторож и брифер",
        "cadence": "daily, before the proposer",
        "cadence_ru": "раз в сутки, перед предлагающим",
        "plain": "Gathers the state into a brief with a hard token "
                 "budget, and writes the owner's summary from the "
                 "same gathering. Two readers, one pass.",
        "plain_ru": "Собирает состояние в бриф с жёстким потолком "
                    "токенов и той же выборкой пишет сводку "
                    "владельцу. Читателя два, проход один.",
        "reads": "the ledger, the run reports, the journal",
        "reads_ru": "журнал объявлений, отчёты прогонов, журнал "
                    "проекта",
        "writes": "brief for the proposer, summary for the owner",
        "writes_ru": "бриф предлагающему, сводку владельцу",
        "forbid": "no claim without a pointer to a file and a number",
        "forbid_ru": "ни одного утверждения без указателя на файл и "
                     "число",
        "doubt": "writes «not measured» rather than "
                 "inventing a number",
        "doubt_ru": "пишет «не измерено», а не выдумывает число",
        "why": "Project memory is 475 169 characters, about 216 "
               "thousand tokens. Paying for it on every call costs "
               "more than the work, and a model reading it whole "
               "proposes from the top of the file.",
        "why_ru": "Память проекта — 475 169 символов, около 216 тысяч "
                  "токенов. Платить за неё каждым вызовом дороже "
                  "самой работы, а модель, читающая её целиком, "
                  "предложит из начала файла. Каденция суточная, "
                  "а не часовая, потому что единственный "
                  "потребитель брифа — предлагающий, и он ходит "
                  "раз в сутки: чаще платить за память незачем.",
        "proof": "research/factory/agents/brief.md",
        # Что роль обязана оставить на диске. Страница показывает эти
        # файлы с размером и возрастом: «роль отработала» без её
        # продукта — утверждение, которое нечем проверить.
        "produces": ["research/factory/out/brief.md",
                     "research/factory/out/summary.md"],
        # Права роли списком, а не режимом «разрешить всё». Первый
        # боевой прогон уткнулся в то, что запись была запрещена, и
        # роль обходила это как могла; лечится это перечнем, а не
        # снятием проверок — граница взрыва у автономной сессии
        # держится правами.
        "tools": ["Read", "Glob", "Grep", "Write", "Edit",
                  "Bash(cat *)", "Bash(tail *)", "Bash(head *)",
                  "Bash(ls *)", "Bash(sed *)", "Bash(wc *)"],
    },
    {
        "key": "propose", "kind": "role", "model": "дорогая",
        "title": "proposer",
        "title_ru": "предлагающий",
        "cadence": "daily",
        "cadence_ru": "раз в сутки",
        "plain": "Reads the brief ONLY and returns a candidate: the "
                 "hypothesis, what would kill it, the cheapest "
                 "calculation that could kill it, and how it differs "
                 "from what is already alive.",
        "plain_ru": "Читает ТОЛЬКО бриф и возвращает кандидата: "
                    "гипотезу, чем она убивается, самый дешёвый "
                    "расчёт, способный её убить, и чем она "
                    "отличается от уже живых.",
        "reads": "the brief",
        "reads_ru": "бриф",
        "writes": "a proposal and a spec file",
        "writes_ru": "предложение и спеку файлом",
        "forbid": "may not read outcomes of candidates it is "
                  "proposing against, and may not re-declare a "
                  "retired candidate under a new name",
        "forbid_ru": "не вправе объявлять заново вылетевшего "
                     "кандидата под новым именем",
        "doubt": "proposes nothing; an empty day is a legitimate "
                 "answer, a filler candidate spends the budget of "
                 "proof",
        "doubt_ru": "не предлагает ничего; пустой день — законный "
                    "ответ, а кандидат для галочки тратит бюджет "
                    "доказательства",
        "why": "Verdicts are forward-only, so data arrives one day "
               "per day. Throughput is set by how many INDEPENDENT "
               "candidates the record can judge, not by how fast "
               "code gets written.",
        "why_ru": "Вердикт выносится только вперёд, и данные приходят "
                  "со скоростью одни сутки в сутки. Пропускная "
                  "способность задана тем, сколько НЕЗАВИСИМЫХ "
                  "кандидатов запись способна рассудить, а не тем, "
                  "как быстро пишется код.",
        "proof": "research/factory/agents/propose.md",
    },
    {
        "key": "ceiling", "kind": "mech", "model": "нет",
        "title": "ceiling",
        "title_ru": "потолок",
        "cadence": "on each proposal",
        "cadence_ru": "на каждое предложение",
        "plain": "Runs the cheap calculation the proposal declared, "
                 "with perfect foresight where that is the only way. "
                 "Fails it and no code is written at all.",
        "plain_ru": "Считает дешёвый расчёт, объявленный в "
                    "предложении, при необходимости с идеальным "
                    "знанием будущего. Не прошёл — кода не пишется "
                    "вовсе.",
        "reads": "the spec and the record",
        "reads_ru": "спеку и запись",
        "writes": "«closed by ceiling» into the ledger",
        "writes_ru": "«закрыто потолком» в журнал объявлений",
        "forbid": "the ceiling is declared BEFORE it is computed and "
                  "is not softened afterwards",
        "forbid_ru": "потолок объявляется ДО расчёта и после него не "
                     "смягчается",
        "doubt": "cannot be computed — says so and the candidate "
                 "waits, it does not pass by default",
        "doubt_ru": "посчитать нечем — так и говорит, кандидат ждёт, "
                    "а не проходит по умолчанию",
        "why": "The cheapest closures in this project were ceilings "
               "computed before building: S1 closed three levers in "
               "an evening, R5's maker ceiling saved weeks, D1's "
               "passive-entry measurement closed the last lever of "
               "hypothesis 7.",
        "why_ru": "Самые дешёвые закрытия в проекте были потолками, "
                  "посчитанными до постройки: S1 закрыл три рычага "
                  "за вечер, мейкерский потолок R5 сэкономил недели, "
                  "замер пассивного входа D1 закрыл последний рычаг "
                  "гипотезы 7.",
        "proof": "research/factory/ceiling.py",
    },
    {
        "key": "build", "kind": "role", "model": "средняя",
        "title": "builder",
        "title_ru": "строитель",
        "cadence": "on demand",
        "cadence_ru": "по требованию",
        "plain": "Writes the candidate's module against the spec, "
                 "plus the mandatory gates: the lookahead test, the "
                 "calibration pair, the moment null, and a loud "
                 "refusal when outcomes come out zero.",
        "plain_ru": "Пишет модуль кандидата по спеке и обязательные "
                    "ворота: тест на заглядывание, калибровочную "
                    "пару, нуль момента и громкий отказ, когда "
                    "исходов вышло ноль.",
        "reads": "the spec",
        "reads_ru": "спеку",
        "writes": "the module and its tests under the candidate's "
                  "own directory",
        "writes_ru": "модуль и его тесты в собственном каталоге "
                     "кандидата",
        "forbid": "writes nowhere outside that directory; a gate "
                  "whose negative control does not bite is not a gate",
        "forbid_ru": "не пишет никуда вне своего каталога; ворота, "
                     "чей негативный контроль не кусается, воротами "
                     "не являются",
        "doubt": "a gate that cannot be built means the candidate is "
                 "not declarable, and that is written down",
        "doubt_ru": "ворота, которых не построить, означают, что "
                    "кандидат необъявляем, и это записывается",
        "why": "This project found about ten lookahead defects, and "
               "EVERY one was found by a person reading a number "
               "that looked wrong. An autonomous session has no such "
               "reader, so the checks must be mechanical.",
        "why_ru": "Проект нашёл около десяти дефектов заглядывания в "
                  "будущее, и КАЖДЫЙ нашёл человек, прочитав число, "
                  "которое выглядело неправильно. У автономной "
                  "сессии читателя нет, значит проверки обязаны быть "
                  "машинными.",
        "proof": "research/factory/agents/build.md",
    },
    {
        "key": "adversary", "kind": "role", "model": "дорогая",
        "title": "adversary",
        "title_ru": "адверсарий",
        "cadence": "before every declaration, with a veto",
        "cadence_ru": "перед каждым объявлением, с правом вето",
        "plain": "Its only job is to break the finding and the "
                 "judge's harness: does the lookahead test bite when "
                 "faked, does the fixture look like a live artifact, "
                 "does the number stand on five episodes, is the "
                 "null honest, does the sign hold across halves.",
        "plain_ru": "Его единственная задача — сломать находку и "
                    "харнесс судьи: кусается ли тест на заглядывание "
                    "при подделке, выглядит ли фикстура как живой "
                    "артефакт, не стоит ли число на пяти эпизодах, "
                    "честен ли нуль, держится ли знак по половинам.",
        "reads": "the module, its tests, the spec, the artifacts",
        "reads_ru": "модуль, его тесты, спеку, артефакты",
        "writes": "a refutation verdict; a veto stops the "
                  "declaration",
        "writes_ru": "вердикт-опровержение; вето останавливает "
                     "объявление",
        "forbid": "may not fix what it broke — it reports, the "
                  "builder repairs",
        "forbid_ru": "не вправе чинить сломанное — он докладывает, "
                     "чинит строитель",
        "doubt": "cannot break it and cannot confirm it either — "
                 "says exactly that, which is not a pass",
        "doubt_ru": "сломать не смог и подтвердить не может — так и "
                    "говорит, и это не «прошёл»",
        "why": "The proposer wants its idea to live, the builder "
               "wants its code to run, the judge wants a result. "
               "Nobody in that line is paid to kill a finding.",
        "why_ru": "Предлагающий хочет, чтобы идея жила, строитель — "
                  "чтобы код работал, судья — чтобы был результат. "
                  "Ни у кого в этой цепочке нет задачи убить "
                  "находку.",
        "proof": "research/factory/agents/adversary.md",
    },
    {
        "key": "declare", "kind": "mech", "model": "нет",
        "title": "declaration",
        "title_ru": "объявление",
        "cadence": "when the adversary lets it through",
        "cadence_ru": "когда адверсарий пропустил",
        "plain": "Writes the candidate into an append-only ledger "
                 "with the COMMIT of its code, not a path to a file. "
                 "From this moment it is judged only forward.",
        "plain_ru": "Пишет кандидата в append-only журнал вместе с "
                    "КОММИТОМ его кода, а не путём к файлу. С этого "
                    "момента он судится только вперёд.",
        "reads": "the verdict of the adversary",
        "reads_ru": "вердикт адверсария",
        "writes": "one immutable line in the ledger",
        "writes_ru": "одну неизменяемую строку журнала",
        "forbid": "nothing rewrites a declared line, ever",
        "forbid_ru": "объявленную строку не переписывает ничто и "
                     "никогда",
        "doubt": "a candidate that cannot be pinned to a commit is "
                 "not declared",
        "doubt_ru": "кандидат, которого нечем привязать к коммиту, "
                    "не объявляется",
        "why": "Forward-only judging is the one defence against the "
               "R5 error that cannot be walked around afterwards. "
               "Without a pinned commit «I keep the survivors» "
               "quietly becomes «I edited until it survived».",
        "why_ru": "Вердикт вперёд — единственная защита от ошибки "
                  "R5, которую нельзя обойти задним числом. Без "
                  "пришпиленного коммита «оставляю выживших» тихо "
                  "становится «правил, пока не выжило».",
        "proof": "research/factory/ledger.py",
    },
    {
        "key": "judge", "kind": "mech", "model": "нет",
        "title": "judge",
        "title_ru": "судья",
        "cadence": "daily",
        "cadence_ru": "раз в сутки",
        "plain": "Replays every live candidate, publishes ALL of "
                 "them, marks what survived, and measures the null "
                 "and the effective N. Selection for publication is "
                 "mechanical on purpose.",
        "plain_ru": "Прогоняет всех живых кандидатов, публикует ВСЕХ, "
                    "помечает выживших и меряет нуль и эффективное "
                    "N. Отбор публикации механический намеренно.",
        "reads": "the ledger and the record",
        "reads_ru": "журнал объявлений и запись",
        "writes": "the daily report with every candidate in it",
        "writes_ru": "суточный отчёт со всеми кандидатами",
        "forbid": "never publishes a top without the null line "
                  "beside it",
        "forbid_ru": "никогда не печатает топ без строки нуля рядом",
        "doubt": "zero outcomes means the reading is broken: it "
                 "refuses to write a report at all",
        "doubt_ru": "ноль исходов означает, что чтение сломано: "
                    "отчёт не пишется вовсе",
        "why": "«Publish only the interesting» IS the R5 "
               "machine: at 96 declared cells the best PURE NOISE "
               "cell showed Sharpe 1.19 against the observed 1.08. "
               "The denominator must live outside every agent.",
        "why_ru": "«Публиковать только интересное» и ЕСТЬ машина "
                  "ошибки R5: при 96 объявленных ячейках лучшая "
                  "ПУСТЫШКА показала Sharpe 1.19 против наблюдённых "
                  "1.08. Знаменатель обязан жить вне всех агентов.",
        "proof": "research/factory/run_day.py",
    },
    {
        "key": "retire", "kind": "mech", "model": "нет",
        "title": "retirement",
        "title_ru": "вылет",
        "cadence": "daily",
        "cadence_ru": "раз в сутки",
        "plain": "Retires a candidate by the SUM of a calendar "
                 "window, not by a streak of red days, and frees its "
                 "slot.",
        "plain_ru": "Отправляет кандидата в вылет по СУММЕ "
                    "календарного окна, а не по серии красных дней, "
                    "и освобождает слот.",
        "reads": "the daily nets of each candidate",
        "reads_ru": "дневные деньги каждого кандидата",
        "writes": "a retirement line in the ledger",
        "writes_ru": "строку вылета в журнале",
        "forbid": "a retired candidate does not come back under "
                  "another name",
        "forbid_ru": "вылетевший кандидат не возвращается под другим "
                     "именем",
        "doubt": "too young to judge is not the same as good: it "
                 "waits, and the report says so",
        "doubt_ru": "«слишком молод, чтобы судить» не равно "
                    "«хорош»: он ждёт, и отчёт это говорит",
        "why": "A dead book fails a ten-day STREAK rule only about "
               "2 % of months, so a hundred slots would fill with "
               "zombies in twenty days.",
        "why_ru": "Дохлая книга заваливает правило десяти красных "
                  "дней ПОДРЯД примерно в 2 % месяцев, то есть сто "
                  "слотов забились бы зомби за двадцать суток.",
        "proof": "research/factory/pool.py",
    },
    {
        "key": "publish", "kind": "mech", "model": "нет",
        "title": "publication",
        "title_ru": "публикация",
        "cadence": "after every run",
        "cadence_ru": "после каждого прогона",
        "plain": "Commits the report and the ledger to the branch "
                 "and puts them on this page. This is the whole "
                 "surface the owner watches.",
        "plain_ru": "Коммитит отчёт и журнал в ветку и выкладывает "
                    "их на эту страницу. Это и есть вся поверхность, "
                    "за которой наблюдает владелец.",
        "reads": "the run artifacts",
        "reads_ru": "артефакты прогона",
        "writes": "the branch and the page",
        "writes_ru": "ветку и страницу",
        "forbid": "a publish command is never allowed to record "
                  "deletions",
        "forbid_ru": "команда публикации не вправе записывать "
                     "удаления ни при каких условиях",
        "doubt": "refuses to commit a file carrying conflict markers",
        "doubt_ru": "отказывается коммитить файл с маркерами "
                    "конфликта",
        "why": "A run whose report stays on the server is "
               "indistinguishable from a run that never happened. "
               "That has already cost this project whole runs.",
        "why_ru": "Прогон, чей отчёт остался на сервере, неотличим "
                  "от прогона, которого не было. Это уже стоило "
                  "проекту целых прогонов.",
        "proof": "tools/publish.sh",
    },
]

# Чего не касается НИ ОДИН агент. Это не удобство, а граница взрыва:
# автономную сессию нельзя остановить посреди прогона, поэтому
# ограничивает её не надзор, а права.
BOUNDARIES = [
    {
        "what": "exchange keys and the live executor",
        "what_ru": "ключи биржи и живой исполнитель",
        "why": "Live money is never automatic. The whitelist of "
               "books allowed real money is the owner's decision, "
               "not a copy of the book list, and the factory does "
               "not widen it.",
        "why_ru": "Живые деньги — никогда автоматом. Белый список "
                  "книг, допущенных к настоящим деньгам, — решение "
                  "владельца, а не копия списка книг, и фабрика его "
                  "не расширяет.",
    },
    {
        "what": "the order-book recording",
        "what_ru": "запись стакана",
        "why": "The only irreplaceable thing in the project: there "
               "is no archive of the book anywhere, and missing days "
               "cannot be fetched later.",
        "why_ru": "Единственное невосстановимое в проекте: архива "
                  "книги нет нигде, и недостающие сутки не докачать.",
    },
    {
        "what": "the ledger, backwards",
        "what_ru": "журнал объявлений задним числом",
        "why": "Append-only. The count of declarations is the "
               "denominator of proof, and no agent may see it as a "
               "setting.",
        "why_ru": "Только дозапись. Число объявлений — знаменатель "
                  "доказательства, и ни один агент не вправе видеть "
                  "его как настройку.",
    },
    {
        "what": "thresholds, once results are visible",
        "what_ru": "пороги, когда результат уже виден",
        "why": "A project rule older than the factory: thresholds "
               "are not changed after the numbers are known. It "
               "exists precisely for moments when changing one would "
               "be reasonable.",
        "why_ru": "Правило проекта старше фабрики: пороги не "
                  "меняются после того, как числа известны. Оно и "
                  "существует ради моментов, когда изменить порог "
                  "выглядит разумным.",
    },
]

# Отказы, которые такая схема создаёт САМА. Названы до постройки: то,
# что названо заранее, ловится дешевле.
RISKS = [
    {
        "title": "agents write plausible text to each other",
        "title_ru": "агенты пишут друг другу правдоподобный текст",
        "guard": "every claim in a brief carries a pointer to a file "
                 "and a number; the adversary spot-checks briefs "
                 "against the artifacts. A claim without a pointer "
                 "is not a brief.",
        "guard_ru": "каждое утверждение брифа несёт указатель на файл "
                    "и число; адверсарий выборочно сверяет брифы с "
                    "артефактами. Утверждение без указателя брифом "
                    "не является.",
    },
    {
        "title": "an agent cannot ask a question",
        "title_ru": "агент не может задать вопрос",
        "guard": "every prompt carries an «at doubt» line: "
                 "do not guess, write «not measured», stop. "
                 "Ambiguity resolved by a model is resolved "
                 "plausibly, which is worse than not at all.",
        "guard_ru": "в каждом промпте строка «при сомнении»: не "
                    "угадывать, записать «не измерено», "
                    "остановиться. Неоднозначность, решённая "
                    "моделью, решается правдоподобно, а это хуже, "
                    "чем никак.",
    },
    {
        "title": "a run dies halfway",
        "title_ru": "прогон умирает посередине",
        "guard": "state lives on disk, not in the agent's head; "
                 "every step is repeatable without harm; the ledger "
                 "is append-only so the next run reads on and "
                 "continues.",
        "guard_ru": "состояние живёт на диске, а не в голове агента; "
                    "каждый шаг повторяем без вреда; журнал "
                    "append-only, поэтому следующий прогон дочитает "
                    "и продолжит.",
    },
    {
        "title": "more candidates than the calendar can judge",
        "title_ru": "кандидатов больше, чем календарь способен "
                    "рассудить",
        "guard": "effective N is MEASURED through the correlation of "
                 "daily money, not counted nominally: a hundred "
                 "books correlated 0.9 carry less than ten "
                 "independent ones.",
        "guard_ru": "эффективное N ИЗМЕРЯЕТСЯ связью дневных денег, "
                    "а не считается номинально: сто книг со связью "
                    "0.9 несут меньше, чем десять независимых.",
    },
    {
        "title": "the cheapest failure of all: silence",
        "title_ru": "самый дешёвый отказ из всех — тишина",
        "guard": "a scheduler that stopped looks exactly like a "
                 "quiet day. Every wake-up leaves a line, and the "
                 "absence of that line is an alarm on this page.",
        "guard_ru": "остановившаяся запускалка выглядит ровно как "
                    "спокойный день. Каждое пробуждение оставляет "
                    "строку, и её отсутствие — тревога на этой "
                    "странице.",
    },
]


def pipeline():
    """Конвейер в порядке исполнения."""
    return list(PIPELINE)


def roles():
    """Шаги, которые ведёт модель."""
    return [s for s in PIPELINE if s["kind"] == "role"]


def mech():
    """Шаги механические — кода достаточно."""
    return [s for s in PIPELINE if s["kind"] == "mech"]


def by_key(key):
    for s in PIPELINE:
        if s["key"] == key:
            return s
    return None


def missing_translations():
    """Записи без русской половины — для теста полноты.

    Приписать шаг и забыть перевод есть молчаливый отказ: страница
    показала бы английский абзац вперемешку с русскими и выглядела
    бы исправной.
    """
    bad = []
    for s in PIPELINE:
        for f in BILINGUAL:
            if not (s.get(f) or "").strip():
                bad.append((s["key"], f))
            elif not (s.get(f + "_ru") or "").strip():
                bad.append((s["key"], f + "_ru"))
    for name, rows, fields in (("boundary", BOUNDARIES,
                                ("what", "why")),
                               ("risk", RISKS, ("title", "guard"))):
        for i, r in enumerate(rows):
            for f in fields:
                if not (r.get(f) or "").strip():
                    bad.append((f"{name}[{i}]", f))
                elif not (r.get(f + "_ru") or "").strip():
                    bad.append((f"{name}[{i}]", f + "_ru"))
    return bad


def tools(key):
    """Разрешённые роли инструменты. Пусто — значит не объявлены."""
    st = by_key(key) or {}
    return list(st.get("tools") or [])
