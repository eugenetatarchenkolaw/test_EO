# Форматы сдачи

Основа — раздел III утвержденной «Постановка_кейса_3.docx». Имена и обязательные поля ниже соответствуют ему. Дополнительные поля и промежуточные файлы разрешены.

Один запуск — один S1-чип, один зафиксированный портфель и заданный бюджет. После изменения бюджета создайте новый комплект либо явно обозначьте версию. CSV: UTF-8, запятая, десятичная точка. Для отсутствующих измерений используйте пустое поле; NaN/Inf и подстановка нуля недопустимы. JSON/GeoJSON также не содержат NaN/Inf.

[Списки столбцов CSV](../schemas/columns.json) · [Пустые формы](../examples/empty_submission). Формы не содержат решения и не являются готовой сдачей.

## GitVerse и воспроизведение

README команды содержит ссылку на официальный Sen1Floods11, commit, версии зависимостей и команды получения/подготовки данных, разбиения, настройки baseline, обучения основного метода, экспериментов и независимой проверки, inference на другом официальном S1, расчета объектов и A/B/C, пересчета бюджета, запуска интерфейса и экспорта.

В GitVerse размещаются весь используемый код, обученная модель и файлы весов; допустимы Git LFS и релизы GitVerse. Укажите версии и контрольные суммы. Внешняя ссылка на веса не заменяет их размещение в GitVerse. Весь исходный Sen1Floods11 повторно публиковать не требуется.

## Файлы и результаты

### flood_probability.tif

Итоговая карта основного метода: GeoTIFF Float32, один канал вероятности воды p от 0 до 1; nodata = −9999. CRS, transform, размеры и пиксельная сетка совпадают с выбранным S1-чипом.

### flood_mask.tif

Бинарная карта основного метода на той же сетке: GeoTIFF UInt8, 1 — вода, 0 — не вода, 255 — nodata. Для каждого валидного пикселя mask = 1 тогда и только тогда, когда p ≥ threshold из run_metadata.json.

### assets.geojson

Единый исходный портфель: FeatureCollection ровно из 10 Point в WGS84 (долгота, широта). Свойства: asset_id, chip_id, asset_class, asset_value_rub, vulnerability_coef; по одному объекту каждого типа и значения V/q из таблицы кейса.

### assets.csv

Табличная копия тех же 10 объектов: asset_id, chip_id, asset_class, asset_value_rub, vulnerability_coef, longitude, latitude. Значения и координаты должны совпадать с assets.geojson; связь с другими файлами — по asset_id.

### asset_loss.csv

Ожидаемый ущерб единого портфеля по основному методу: по строке на каждый asset_id. Поля: asset_id, chip_id, p_flood, expected_loss_rub, uncertainty, rank, status. p_flood извлекается из flood_probability.tif независимо от бинарной маски; EL = p_flood × V × q из assets.csv. rank: 1 — максимальный EL, при равенстве — по asset_id. Для status=partial/no_data неоцененные p/EL/rank — пустые, не нулевые; смысл неопределенности и статус раскрыты в run_metadata.json.

### candidate_orders.geojson

Единый каталог ВСЕХ предложенных зон, а не только выбранных. FeatureCollection из валидных Polygon WGS84 без внутренних вырезов, площадью от 1 км² каждый. Поля: candidate_id, sensor_type, resolution_m, acquisition_type (new/operational/archive), data_role (event_observation/context), observation_at, available_at, processing_level (L0/L1/L2), usage_type (internal/limited/unrestricted), guaranteed_purchase (true/false), area_km2, base_rate_rub_km2, base_rate_status, base_rate_source. Неизвестная дата будущего наблюдения оставляется пустой или объявляется сценарной, ее статус и доступность к сроку решения раскрыты в run_metadata.json. Для уже имеющихся снимков guaranteed_purchase=false; гарантированная покупка новой съемки указывается явно.

### procurement_plan.csv

Детализация платных заказов B и C (для A строк нет): strategy, candidate_id, area_km2, base_rate_rub_km2, base_rate_status, processing_level, usage_type, guaranteed_purchase, processing_coef, usage_coef, freshness_coef, discount_coef, discount_group_id, group_area_km2, unit_price_rub_km2, cost_rub, formula, legal_edition. Каждая пара (strategy, candidate_id) уникальна; зоны связываются с candidate_orders.geojson; категориальные условия совпадают с каталогом и объясняют выбор коэффициентов (для guaranteed_purchase в CSV используйте true/false). Скидка пересчитывается для каждой корзины целиком, итоговая цена стратегии — сумма ее строк. Пустой план C допустим при отсутствии заказов в пределах бюджета.

### strategy_plans.json

Точные составы стратегий: JSON-объект вида {"A": [], "B": ["candidate_id"], "C": ["candidate_id"]}; фактически подставляются все выбранные идентификаторы. A — без платных зон; B и C используют только candidate_id из candidate_orders.geojson. Списки совпадают со строками procurement_plan.csv соответствующих стратегий.

### strategy_comparison.csv

Итог по каждой стратегии A/B/C: strategy, data_cost_rub, other_cost_rub, decision_cost_rub, budget_rub, budget_feasible, covered_expected_loss_rub, coverage_share, residual_uncertainty, uncertainty_status, uncertainty_basis. budget_rub ограничивает data_cost_rub; decision_cost_rub = data_cost_rub + other_cost_rub (прочие статьи отдельно); C соблюдает лимит, B может быть контрфактической. Для A residual_uncertainty — исходная неопределенность со статусом baseline; для B/C без новых наблюдений ее не снижают автоматически: сценарный эффект — scenario с формулой, реально проверенный — measured, отсутствие оценки — not_estimated с пустым числовым полем. Охват уникален по asset_id; единицы/агрегация раскрыты в run_metadata.json.

### sensitivity.csv

Проверка устойчивости: scenario_id, strategy, changed_inputs_json, decision_cost_rub, covered_expected_loss_rub, result_status, interpretation. Одна строка — один вариант параметров и итоговый пересчет; changed_inputs_json содержит, что именно изменено (например, бюджет или V/q), а interpretation — как и почему поменялся план.

### run_metadata.json

Паспорт одного комплекта результатов: run_id, исходный chip_id и event_id, источник/S1-файлы и split, seed и правило размещения, commit GitVerse, версии/веса обоих методов, их пороги и порядок проверки, используемая модель EL, бюджет и deadline, тариф и правила скидки, построение и доступность зон, единицы и расчет неопределенности, протокол и результат прокси-проверки ущерба (на каком test, какие контрольные точки, фиксированные V/q, число точек, метрика ошибки), ссылки на файлы метрик и команды воспроизведения.

### source_manifest.json

Манифест всех исходных данных, включая обязательный S1 и использованные дополнительные источники: для каждого — идентификатор/файл, URL, версия, дата наблюдения и дата публикации/доступности, лицензия, назначение и ограничения. Метки и дополнительные данные привязаны к применимым фрагментам.

### Интерфейс

Инструмент работы оператора, а не файл с фиксированным именем: показывает исходный S1, вероятность/маску, 10 объектов с EL и неопределенностью, кандидатные и выбранные зоны с ценой и сроками, A/B/C и чувствительность. Изменение бюджета пересчитывает C и результаты; README содержит команду запуска или URL и способ выгрузки комплекта.

## Метрики и результаты baseline

По критериям № 2, 4 и 12 также сдаются бинарная маска baseline и метрики обоих методов: IoU, F1/Dice, Precision, Recall и число общих валидных тестовых пикселей, с разбором по событиям/участкам. Имена этих дополнительных файлов постановка не фиксирует: укажите их в README и `run_metadata.json`. Вероятностный растр и экономический расчет baseline не обязательны.

Конкретная вложенная структура паспортов JSON, формат отчета об экспериментах и дизайн интерфейса остаются за командой при сохранении указанного содержания. Готовый валидатор результатов не выдается; команда публикует собственные проверки в GitVerse. [Что проверить](VALIDATION.md).
