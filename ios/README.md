# Algoth — приложение для iPhone и iPad

Приложение проекта целиком; первый экран — DCA. Экраны **родные** (SwiftUI),
не страница в браузере: данные берутся из тех же ответов сервера наблюдения,
что кормят страницы (`/dca` — свод раз в минуту, `/dca_marks` — живая
отметка открытых раз в 10 с). Деньги считает сервер; приложение печатает
пришедшее теми же форматами, что страница (`Format.swift` ↔ `usd`, `fpct`,
`tsq`, `qtyf` в `web.py`). Новое поле свода появится в приложении только
новой сборкой — в этом цена родного экрана.

Открывается сразу на DCA: адрес сервера и ключ страницы вшиты сборкой
(секрет `ALGOTH_PAGE_KEY`); в git ключа нет. Отказ — словами («ключ не
подошёл», «сборщик не отвечает»), прошлые числа при отказе остаются под
красной плашкой со временем.

iPhone — одна колонка и нижняя панель (накопленный счёт, открыто / мест,
прыжок к журналу); iPad — плитки, сутки и позиции сеткой в несколько колонок.
Позиция по нажатию — лестница (каждый вход, ТВХ после него, выход) и график
позиции (страница сервера во встроенном Safari).

## Что нужно один раз от владельца

Собирает и отправляет в TestFlight GitHub Actions на маке
(`.github/workflows/ios-testflight.yml`); своего мака не нужно.

1. **Apple Developer Program** — аккаунт организации MDS Auto (sp. z o.o.).
   Для TestFlight с внутренним тестированием компания ничего не меняет: имя
   продавца видно только при публикации в App Store. Ключ API с ролью Admin
   создаёт только Account Holder или Admin команды.
2. **Идентификатор приложения.** developer.apple.com → Certificates,
   Identifiers & Profiles → Identifiers → «+» → App IDs → App → описание
   «Algoth», Bundle ID явный: `pl.mdsauto.algoth`.
3. **Запись приложения.** appstoreconnect.apple.com → Apps → «+» → New App:
   платформа iOS, имя «Algoth» (если занято — например «Algoth Trading»), язык русский,
   Bundle ID из шага 2, SKU любой (`algoth`).
4. **Ключ API.** App Store Connect → Users and Access → Integrations →
   App Store Connect API → Team Keys → «+», роль **Admin** (меньшая роль не
   даёт облачной подписи). Скачать `.p8` (дают один раз), записать Key ID и
   Issuer ID.
5. **Team ID** команды MDS Auto — developer.apple.com → Membership details, 10 знаков.
6. **Секреты репозитория** — github.com/n0tgod/algoth_v2 → Settings →
   Secrets and variables → Actions → New repository secret, пять штук:

   | имя | что |
   |---|---|
   | `ASC_KEY_ID` | Key ID из шага 4 |
   | `ASC_ISSUER_ID` | Issuer ID из шага 4 |
   | `ASC_KEY_P8` | содержимое файла `.p8` целиком, с строками BEGIN/END |
   | `APPLE_TEAM_ID` | Team ID из шага 5 |
   | `IOS_BUNDLE_ID` | `pl.mdsauto.algoth` |
   | `ALGOTH_PAGE_KEY` | ключ страниц сервера (что после `?k=`) |

7. **Запуск.** GitHub → Actions → iOS TestFlight → Run workflow (или любой
   пуш в `ios/`). Прогон ~10 минут, затем Apple обрабатывает сборку ещё
   10–20 минут.
8. **TestFlight.** App Store Connect → приложение → TestFlight → Internal
   Testing → «+» группа → добавить себя. На iPhone и iPad поставить
   TestFlight из App Store, войти тем же Apple ID → «Algoth» → Install.
   Внутренние тестировщики — только пользователи команды MDS Auto в App
   Store Connect.
9. **Первый запуск** — сразу экран DCA, вводить ничего не нужно.

Сборка помечена «только для внутреннего тестирования»: проверки Apple
(beta review) ей не нужно, ставится сразу после обработки. Сборка
TestFlight живёт 90 дней — дальше новый прогон.

## Без секретов

Прогон всё равно собирает приложение под симулятор — это проверка, что код
компилируется, — и пишет в сводку предупреждение, что загрузки не было.

## Устройство

| файл | что |
|---|---|
| `project.yml` | проект Xcode для XcodeGen; `.xcodeproj` генерируется и в git не идёт |
| `Algoth/AlgothApp.swift` | вход |
| `Algoth/API.swift` | сервер и ключ из сборки, запрос, отказы словами, терпимый разбор JSON (`J`) |
| `Algoth/Format.swift` | форматы чисел — копия форматов страницы |
| `Algoth/DCAModel.swift` | выбор книги, загрузка, ритм опроса, общий список позиций |
| `Algoth/DCAView.swift` | экран: фильтры, книга, общий счёт, дубли, нижняя панель |
| `Algoth/StatSection.swift` | главные плитки, издержки, метрики, кривая (Swift Charts) |
| `Algoth/Sections.swift` | сутки, короткие книги, позиции карточками |
| `Algoth/PositionDetail.swift` | лестница позиции, график, «что это» |
| `Algoth/Theme.swift` | палитра и элементы страницы |
| `ExportOptions.plist` | выгрузка в App Store Connect, только внутреннее тестирование |

**Данные ходят по http** — у сервера нет сертификата (`NSAllowsArbitraryLoads`).
Ключ лежит внутри сборки: годится, пока сборка только для внутреннего
тестирования.
