"""Rebuild published figures from cited table values and the tariff equation."""
from pathlib import Path
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).parents[1]
OUT = ROOT / "docs/figures"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": "#243746", "text.color": "#243746",
                     "axes.edgecolor": "#aab6be", "svg.fonttype": "none",
                     "svg.hashsalt": "floodvalue-v1", "figure.facecolor": "white"})
BLUE, GOLD = "#226b94", "#b67d23"


def save(fig, name, note):
    fig.text(.04, .04, note, fontsize=9, color="#526774", va="bottom")
    fig.savefig(OUT / (name + ".svg"), metadata={"Date": None}, facecolor="white")
    svg_path = OUT / (name + ".svg")
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n")
    preview = ROOT / "outputs/figure_previews"
    preview.mkdir(parents=True, exist_ok=True)
    fig.savefig(preview / (name + ".png"), dpi=130)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "data/evidence/sen1floods11_table1.csv").open() as f:
        rows = list(csv.DictReader(f))
    labels = ["Обучение: S1 weak", "Обучение: S2 weak", "Обучение: ручные метки",
              "Обучение: постоянная вода", "Порог Otsu, VH"]
    values = [float(r["flood_water_mean_iou"]) for r in rows]
    fig, ax = plt.subplots(figsize=(11.8, 5.7))
    fig.subplots_adjust(left=.31, right=.93, top=.76, bottom=.23)
    fig.text(.04, .91, "Sen1Floods11: качество на паводковой воде", fontsize=19, weight="bold")
    fig.text(.04, .84, "Средний IoU по фрагментам · 10 событий, без Bolivia · таблица 1", fontsize=12)
    bars = ax.barh(labels, values, color=BLUE, height=.57)
    ax.invert_yaxis(); ax.set_xlim(0, .4)
    ax.xaxis.set_major_formatter(PercentFormatter(1)); ax.set_xlabel("Mean IoU, класс flood water")
    ax.set_axisbelow(True); ax.grid(axis="x", color="#e5eaee")
    ax.tick_params(axis="y", length=0, pad=12)
    for bar, value in zip(bars, values):
        ax.text(value+.008, bar.get_y()+bar.get_height()/2, f"{value*100:.2f}%", va="center", fontsize=11)
    save(fig, "sen1floods11", "Источник: Bonafilia et al., CVPRW 2020, табл. 1. DOI: 10.1109/CVPRW50498.2020.00113.\nИсторический эксперимент; не результат FloodValue и не норматив качества для команд.")
    rows = np.genfromtxt(ROOT / "data/evidence/jrc_table5_4.csv", delimiter=",", names=True)
    fig, ax = plt.subplots(figsize=(11.8, 5.8))
    fig.subplots_adjust(left=.11, right=.95, top=.75, bottom=.25)
    fig.text(.04, .91, "Глубина воды и доля прямого ущерба", fontsize=19, weight="bold")
    fig.text(.04, .84, "Глобальные обобщенные функции JRC · пример зависимости, не калибровка для России", fontsize=11.5)
    ax.plot(rows["depth_m"], rows["agriculture_fraction"], "o-", color=BLUE, label="Сельское хозяйство", lw=2)
    ax.plot(rows["depth_m"], rows["infrastructure_fraction"], "s--", color=GOLD, label="Инфраструктура", lw=2)
    ax.set(xlim=(0,6), ylim=(0,1.04), xlabel="Глубина затопления, м", ylabel="Доля ущерба")
    ax.yaxis.set_major_formatter(PercentFormatter(1)); ax.grid(color="#e5eaee"); ax.legend(frameon=False, loc="lower right")
    save(fig, "depth_damage", "Источник: Huizinga, de Moel, Szewczyk, 2017, табл. 5-4, с. 75. DOI: 10.2760/16510.\nГлубина не определяется из вероятности воды; перенос функции требует проверки применимости.")
    area = np.logspace(0,8,120)
    fig, ax = plt.subplots(figsize=(11.8,5.8))
    fig.subplots_adjust(left=.1,right=.94,top=.76,bottom=.25)
    fig.text(.04,.91,"Скидка по ПП № 840 зависит от объема",fontsize=19,weight="bold")
    fig.text(.04,.84,"Редакция 27.08.2025 · расчет при разрешении 1 м · S в км²",fontsize=12)
    for sensor,color,label,style in [("optical",BLUE,"Оптика","-"),("sar",GOLD,"SAR","--")]:
        slope, intercept, floor = (0.058, 1.037, 0.2) if sensor == "optical" else (0.020, 1.031, 0.7)
        y = np.clip(-slope * np.log(area) + intercept, floor, 1)  # Illustration only, r = 1 m.
        ax.plot(area,y,color=color,lw=2,ls=style,label=label)
    ax.set(xscale="log",xlim=(1,1e8),ylim=(0,1.05),xlabel="Площадь S, км² · логарифмическая шкала",ylabel="Коэффициент Р")
    ax.grid(color="#e5eaee");ax.legend(frameon=False,loc="lower left")
    save(fig,"pp840_discount","Источник: ПП РФ № 840, приложение № 4 в редакции ПП РФ № 1297 от 27.08.2025.\nРасчетная зависимость, не предложение поставщика. Нижние границы: оптика 0,2; SAR 0,7.")


if __name__ == "__main__":
    main()
