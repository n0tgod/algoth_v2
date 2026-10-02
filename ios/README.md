# Algoth DCA — приложение для iPhone и iPad

Оболочка страницы `/dca-page` сборщика B1. Страница в приложение **не
копируется**: её код один (`research/b1_book/web.py`, `DCAPAGE`), приложение
открывает её с сервера с параметром `app=1`. Поэтому любая правка страницы
видна в приложении после `restart-book`, без новой сборки.

Что даёт приложение сверх вкладки Safari:

- ключ хранится в связке ключей устройства, а не в адресе;
- потянуть вниз — перезагрузка; после 5 минут в фоне страница
  перезагружается сама (в фоне iOS её опрос останавливает);
- отказ словами: «ключ не подошёл (403)», «сервер не отвечает» — с кнопками
  «Повторить» и «Настройки»; белого экрана нет;
- меню соседних страниц спрятано, логотип ALGOTH открывает настройки;
- жест «назад» от графика сделки к списку;
- iPhone: отступы под вырез и полосу «домой»; iPad: позиции и сутки
  карточками в две колонки вертикально и в три горизонтально (раньше таблица
  уезжала вбок на 876 px).

## Что нужно один раз от владельца

Собирает и отправляет в TestFlight GitHub Actions на маке
(`.github/workflows/ios-testflight.yml`); своего мака не нужно.

1. **Apple Developer Program** (99 $ в год) — без неё TestFlight недоступен.
2. **Идентификатор приложения.** developer.apple.com → Certificates,
   Identifiers & Profiles → Identifiers → «+» → App IDs → App → описание
   «Algoth DCA», Bundle ID явный, например `com.<ваше-имя>.algothdca`.
3. **Запись приложения.** appstoreconnect.apple.com → Apps → «+» → New App:
   платформа iOS, имя «Algoth DCA» (если занято — любое), язык русский,
   Bundle ID из шага 2, SKU любой (`algothdca`).
4. **Ключ API.** App Store Connect → Users and Access → Integrations →
   App Store Connect API → Team Keys → «+», роль **Admin** (меньшая роль не
   даёт облачной подписи). Скачать `.p8` (дают один раз), записать Key ID и
   Issuer ID.
5. **Team ID** — developer.apple.com → Membership details, 10 знаков.
6. **Секреты репозитория** — github.com/n0tgod/algoth_v2 → Settings →
   Secrets and variables → Actions → New repository secret, пять штук:

   | имя | что |
   |---|---|
   | `ASC_KEY_ID` | Key ID из шага 4 |
   | `ASC_ISSUER_ID` | Issuer ID из шага 4 |
   | `ASC_KEY_P8` | содержимое файла `.p8` целиком, с строками BEGIN/END |
   | `APPLE_TEAM_ID` | Team ID из шага 5 |
   | `IOS_BUNDLE_ID` | Bundle ID из шага 2 |

7. **Запуск.** GitHub → Actions → iOS TestFlight → Run workflow (или любой
   пуш в `ios/`). Прогон ~10 минут, затем Apple обрабатывает сборку ещё
   10–20 минут.
8. **TestFlight.** App Store Connect → приложение → TestFlight → Internal
   Testing → «+» группа → добавить себя. На iPhone и iPad поставить
   TestFlight из App Store, войти тем же Apple ID → «Algoth DCA» → Install.
9. **Первый запуск.** Сервер уже подставлен (`http://116.203.146.99`),
   ввести ключ страницы — тот же, что после `?k=` в адресе страниц.

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
| `AlgothDCA/AlgothDCAApp.swift` | вход, корневой вид, перезагрузка после фона, экран отказа |
| `AlgothDCA/WebView.swift` | `WKWebView`: адрес страницы с `app=1`, 403/сеть словами, свои/чужие ссылки, потянуть-обновить, сообщение `algoth` |
| `AlgothDCA/Settings.swift` | адрес сервера и ключ (связка ключей) |
| `ExportOptions.plist` | выгрузка в App Store Connect, только внутреннее тестирование |

Уговор страницы и приложения (`app=1`, сообщение `algoth`) проверяет
`research/b1_book/test_book.py` → `test_dca_page_fits_the_tablet_and_the_app`.

**Ключ ходит по http** — как и во вкладке браузера: у сервера нет
сертификата. Исключение ATS (`NSAllowsArbitraryLoadsInWebContent`) дано только
веб-содержимому.
