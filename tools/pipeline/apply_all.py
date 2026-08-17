"""
Повне вшивання шрифтів у гру одним прогоном, у ПРАВИЛЬНОМУ порядку.

🔴 Порядок критичний, і ось чому:

1. `add_bold_fallback` — дає жирним варіантам (`ArconBold-...Variant`,
   `friz-...-bold-...Variant`) кириличний запасний. Мусить бути ПЕРШИМ, бо
   наступний крок фільтрує шрифти саме за наявністю кириличного запасного;
   якби він ішов пізніше, у жирних варіантах лишилася б латинська пунктуація
   і `<b>`-фрагмент змішував би гарнітури.
2. `repoint_fonts` — розводить базові шрифти між слотами Fixel/Kyiv
   (+ знімає тултіпи з CJK-заглушок).
3. `hide_base_punct` — ховає 40 символів (пунктуація + цифри) у базових
   шрифтах. Перезаписує ЦІЛІ обʼєкти, тому мусить іти ПІСЛЯ кроків, які
   правлять байти всередині тих самих обʼєктів: інакше його бекап зафіксує
   проміжний стан. Відкат усе одно коректний, бо `restore_all` іде у
   зворотному хронологічному порядку.
4. `inplace_font` + `inplace_resources` — самі гарнітури в кириличні слоти
   (асети + атласи). Ці обʼєкти не перетинаються з базовими шрифтами.
5. `retarget_components` — перецілює `m_fontAsset` окремих компонентів UI там,
   де один шрифт малює і Kyiv-, і Fixel-зміст (тіло превью предмета, фільтри
   скрині, кнопки головного меню, плашка локації). Іде ОСТАННІМ: він править
   компоненти, а не шрифтові асети, і спирається на вже розведені слоти.

Гра має бути ЗАКРИТА. Жоден файл не змінює розміру.

  python apply_all.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, HERE)
import kitconfig  # noqa: E402

STEPS = [
    # 🔴 ПЕРШИМ: обʼєкт росте на 8 Б (у межах проміжку вирівнювання), тому всі
    # зсуви шрифтових правок усередині нього мусять рахуватися вже ПІСЛЯ цього.
    ("fix_hardcoded_text.py", ["apply"], "англійські літерали в компонентах UI"),
    ("add_bold_fallback.py", ["apply"], "кирилиця жирним варіантам"),
    ("repoint_fonts.py", ["apply"], "розведення базових шрифтів по слотах"),
    ("hide_base_punct.py", ["apply"], "приховати пунктуацію й цифри в базових"),
    ("inplace_font.py", ["apply"], "гарнітури в слоти бандла"),
    ("inplace_resources.py", ["apply"], "гарнітури в слоти resources.assets"),
    ("fix_bold_weight.py", ["apply"], "вагова таблиця Fixel-слота (<b> більше не Kyiv)"),
    # 🔴 Друга текстова підсистема гри — UI Toolkit, у неї СВОЇ шрифтові асети
    # (m_Script -> Library/unity default resources 19001) і свої кириличні слоти.
    # Нею намальовані панелі мапи, журналу й активностей. Класи не сумісні:
    # запасний чужого класу = тихий нативний виліт без винятку в лозі.
    ("inplace_uitk.py", ["apply"], "гарнітури в кириличні слоти UI Toolkit"),
    ("repoint_uitk.py", ["apply"], "маршрутизація шрифтів UI Toolkit"),
    ("fix_uitk_chain.py", ["apply"], "стилі журналу/мапи -> слот B, NotInter -> Fixel"),
    # uitkitalic_fix + uitknuke + uitkfinal_styles накладаються ВРУЧНУ окремими
    # журналами (див. HANDOFF). Автоматизувати після фінального підтвердження.
    ("retarget_components.py", ["apply"], "точкове перецілювання компонентів UI"),
]


def run(script, args, title):
    print("\n" + "=" * 74)
    print(f"КРОК: {title}   ({script} {' '.join(args)})")
    print("=" * 74, flush=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                       cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [ln for ln in (r.stdout or "").splitlines()
            if any(k in ln for k in ("записано", "усього", "шрифтів:", "🔴",
                                     "асет:", "набір", "ok "))]
    print("\n".join(tail[-24:]))
    if r.returncode != 0:
        print("STDERR:", (r.stderr or "")[-1500:])
        raise SystemExit(f"КРОК ВПАВ: {script}")
    time.sleep(1.2)          # щоб час створення журналів бекапу відрізнявся


def main():
    if os.path.exists(kitconfig.BACKUP) and os.listdir(kitconfig.BACKUP):
        print("🔴 Тека бекапів не порожня — спершу `python restore_all.py`, "
              "потім видали " + kitconfig.BACKUP)
        return 1
    t0 = time.time()
    for s, a, t in STEPS:
        run(s, a, t)
    print("\n" + "=" * 74)
    print(f"ГОТОВО за {time.time()-t0:.0f} с. Далі: python verify_all.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
