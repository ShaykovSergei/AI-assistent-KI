from dotenv import load_dotenv
load_dotenv('.env')
from anonymizer import anonymize
from gigachat import analyze_request
from normalizer import normalize_result

cases = [
    ("full", "Ирина Соколова", "+7 916 245-18-03", "i.sokolova@alfalogistika.ru",
     "Здравствуйте! Я офис-менеджер компании \"Альфа-Логистик\". Мы переезжаем в новый офис на 40 рабочих мест и хотим заказать поставку и сборку офисной мебели: столы, кресла и шкафы. Переезд — в начале следующего месяца, бюджет около 1,5 млн рублей. Пришлите, пожалуйста, коммерческое предложение."),
    ("non-target", "Алексей Петров", "+7 999 123-45-67", "",
     "Ищем подрядчика на разработку мобильного приложения под IOS и Android."),
    ("complaint", "Максим Волков", "+7 921 300-77-45", "m.volkov@nordgroup.ru",
     "Это уже третье письмо! Заказ должны были привезти в понедельник, сейчас четверг — ни мебели, ни звонка. Менеджер не берёт трубку. Если завтра ничего не изменится, будем отказываться и требовать возврат предоплаты."),
    ("insufficient", "Дмитрий Орлов", "+7 903 771-42-10", "",
     "Добрый день, сколько у вас стоят офисные кресла? Нужно несколько штук.")
]

def build(name, phone, email, text):
    lines = [f"Имя: {name}", f"Телефон: {phone}"]
    if email: lines.append(f"Email: {email}")
    lines.extend(["", "Текст заявки:", text])
    return "\n".join(lines)

for cid, name, phone, email, text in cases:
    req = build(name, phone, email, text)
    anon, mapping = anonymize(req)
    raw = analyze_request(anon)
    res, notes = normalize_result(raw, req)
    print(f"=== {cid} ===")
    print("lead_type:", res["lead_type"], "| needs_human:", res["needs_human"], "| reason:", res["human_reason"])
    print("missing:", res["missing_data"])
    print("next_step:", res["next_step"])
    print("notes:", notes)
    print()
