"""Simulación de colas independientes para el pago de parqueaderos."""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


CATEGORY_PROBABILITIES = {
    "Rápido": 0.25,
    "Normal": 0.20,
    "Lento": 0.275,
    "Muy lento": 0.275,
}
CATEGORY_ORDER = tuple(CATEGORY_PROBABILITIES)
ARRIVAL_MEAN_MINUTES = {
    "Rápido": 3.0,
    "Normal": 3.0,
    "Lento": 5.0,
    "Muy lento": 7.0,
}
SERVICE_MEAN_MINUTES = {
    "Rápido": 1.0,
    "Normal": 3.0,
    "Lento": 4.0,
    "Muy lento": 6.0,
}
CUSTOMERS_PER_REPLICATION = 3000
WARMUP_CUSTOMERS_PER_CASHIER = 30
MIN_REPLICATIONS = 60
BATCH_SIZE = 10
MAX_REPLICATIONS = 500
STABILITY_RELATIVE_TOLERANCE = 0.01
STABILITY_REQUIRED_CHECKS = 5
MIN_WAIT_REDUCTION_PERCENT = 10.0
T95 = {
    2: 12.706,
    3: 4.303,
    4: 3.182,
    5: 2.776,
    6: 2.571,
    7: 2.447,
    8: 2.365,
    9: 2.306,
    10: 2.262,
    11: 2.228,
    12: 2.201,
    13: 2.179,
    14: 2.160,
    15: 2.145,
    16: 2.131,
    17: 2.120,
    18: 2.110,
    19: 2.101,
    20: 2.093,
    21: 2.086,
    22: 2.080,
    23: 2.074,
    24: 2.069,
    25: 2.064,
    26: 2.060,
    27: 2.056,
    28: 2.052,
    29: 2.048,
    30: 2.045,
}


@dataclass(frozen=True)
class Customer:
    arrival_minute: float
    category: str
    service_minutes: float
    route_draw: float


@dataclass(frozen=True)
class Visit:
    arrival_minute: float
    finish_minute: float
    category: str
    wait_minutes: float
    service_minutes: float


@dataclass
class Replication:
    number: int
    customers: list[Customer]
    cashier_visits: dict[int, list[list[Visit]]]


def descriptive_stats(values: Iterable[float]) -> dict[str, float]:
    samples = list(values)
    if not samples:
        raise ValueError("No hay observaciones para calcular estadísticas.")
    average = mean(samples)
    if len(samples) == 1:
        return {"mean": average, "sd": 0.0, "low": average, "high": average}
    deviation = stdev(samples)
    critical = T95.get(len(samples), 1.96)
    margin = critical * deviation / math.sqrt(len(samples))
    return {
        "mean": average,
        "sd": deviation,
        "low": average - margin,
        "high": average + margin,
    }


def generate_customers(rng: random.Random, count: int) -> list[Customer]:
    if count < 1:
        raise ValueError("La cantidad de vehículos debe ser positiva.")

    customers = []
    arrival_minute = 0.0
    for _ in range(count):
        category = rng.choices(
            CATEGORY_ORDER,
            weights=[CATEGORY_PROBABILITIES[item] for item in CATEGORY_ORDER],
            k=1,
        )[0]
        arrival_minute += rng.expovariate(1.0 / ARRIVAL_MEAN_MINUTES[category])
        service_minutes = rng.expovariate(
            1.0 / SERVICE_MEAN_MINUTES[category]
        )
        customers.append(
            Customer(
                arrival_minute=arrival_minute,
                category=category,
                service_minutes=service_minutes,
                route_draw=rng.random(),
            )
        )
    return customers


def route_customers(
    customers: Iterable[Customer],
    cashier_count: int,
) -> list[list[Visit]]:
    """Asigna cada vehículo al azar a una fila independiente FIFO."""
    if cashier_count < 1:
        raise ValueError("Debe existir al menos un cajero.")

    available_at = [0.0] * cashier_count
    visits: list[list[Visit]] = [[] for _ in range(cashier_count)]
    for customer in customers:
        cashier = min(int(customer.route_draw * cashier_count), cashier_count - 1)
        start = max(customer.arrival_minute, available_at[cashier])
        finish = start + customer.service_minutes
        available_at[cashier] = finish
        visits[cashier].append(
            Visit(
                arrival_minute=customer.arrival_minute,
                finish_minute=finish,
                category=customer.category,
                wait_minutes=start - customer.arrival_minute,
                service_minutes=customer.service_minutes,
            )
        )
    return visits


def _trimmed(visits: list[Visit]) -> list[Visit]:
    return visits[WARMUP_CUSTOMERS_PER_CASHIER:]


def _selected_visits(
    replications: list[Replication],
    cashier_count: int,
    cashier_index: int,
    discard_warmup: bool = True,
) -> list[Visit]:
    selected = []
    for replication in replications:
        visits = replication.cashier_visits[cashier_count][cashier_index]
        selected.extend(_trimmed(visits) if discard_warmup else visits)
    return selected


def _replication_wait(
    replication: Replication,
    cashier_count: int,
    discard_warmup: bool = True,
) -> float:
    visits = [
        visit
        for cashier_visits in replication.cashier_visits[cashier_count]
        for visit in (
            _trimmed(cashier_visits) if discard_warmup else cashier_visits
        )
    ]
    return mean(visit.wait_minutes for visit in visits)


def _convergence_means(
    replications: list[Replication],
) -> dict[str, float]:
    return {
        str(cashier_count): mean(
            _replication_wait(replication, cashier_count)
            for replication in replications
        )
        for cashier_count in (3, 4)
    }


def run_experiment(max_replicates: int, seed: int) -> dict:
    if (
        not MIN_REPLICATIONS <= max_replicates <= MAX_REPLICATIONS
        or max_replicates % BATCH_SIZE != 0
    ):
        raise ValueError(
            f"El máximo de réplicas debe ser múltiplo de {BATCH_SIZE} "
            f"entre {MIN_REPLICATIONS} y {MAX_REPLICATIONS}."
        )
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("La semilla debe ser un número entero.")

    replications: list[Replication] = []
    convergence_history = []
    previous_means = None
    stable_streak = 0
    converged = False

    for number in range(1, max_replicates + 1):
        rng = random.Random(seed + number * 1009)
        customers = generate_customers(rng, CUSTOMERS_PER_REPLICATION)
        cashier_visits = {
            count: route_customers(customers, count) for count in (3, 4)
        }
        replications.append(
            Replication(number, customers, cashier_visits)
        )

        if number % BATCH_SIZE:
            continue

        current_means = _convergence_means(replications)
        if previous_means is None:
            max_change_pct = None
            stable_streak = 0
        else:
            max_change_pct = (
                abs(current_means["3"] - previous_means["3"])
                / max(abs(previous_means["3"]), 0.01)
                * 100.0
            )
            stable_streak = (
                stable_streak + 1
                if max_change_pct <= STABILITY_RELATIVE_TOLERANCE * 100.0
                else 0
            )

        convergence_history.append({
            "replications": number,
            "meanWaitThree": mean(
                _replication_wait(replication, 3) for replication in replications
            ),
            "meanWaitFour": mean(
                _replication_wait(replication, 4) for replication in replications
            ),
            "maxChangePct": max_change_pct,
            "stableStreak": stable_streak,
        })
        if stable_streak >= STABILITY_REQUIRED_CHECKS:
            converged = True
            break
        previous_means = current_means

    return {
        "seed": seed,
        "replications": replications,
        "converged": converged,
        "replicationsUsed": len(replications),
        "convergenceHistory": convergence_history,
    }


def _queue_estimate(visit_sets: list[list[Visit]]) -> dict:
    nonempty = [visits for visits in visit_sets if visits]
    if not nonempty:
        return {
            "arrivalRate": 0.0,
            "serviceRate": 0.0,
            "rho": 0.0,
            "stable": False,
            "wq": None,
            "lq": None,
        }

    count = sum(len(visits) for visits in nonempty)
    duration = sum(
        max(visits[-1].finish_minute - visits[0].arrival_minute, 1e-12)
        for visits in nonempty
    )
    service_time = sum(
        visit.service_minutes
        for visits in nonempty
        for visit in visits
    )
    arrival_rate = count / duration
    service_rate = count / service_time if service_time else 0.0
    rho = arrival_rate / service_rate if service_rate else math.inf
    stable = service_rate > arrival_rate
    if stable:
        wq = rho / (service_rate - arrival_rate)
        lq = arrival_rate * wq
    else:
        wq = None
        lq = None
    return {
        "arrivalRate": arrival_rate,
        "serviceRate": service_rate,
        "rho": rho,
        "stable": stable,
        "wq": wq,
        "lq": lq,
    }


def _cashier_summary(
    replications: list[Replication],
    cashier_count: int,
    cashier_index: int,
) -> dict:
    visit_sets = [
        _trimmed(replication.cashier_visits[cashier_count][cashier_index])
        for replication in replications
    ]
    wait_by_replication = [
        mean(visit.wait_minutes for visit in visits) for visits in visit_sets
    ]
    service_by_replication = [
        mean(visit.service_minutes for visit in visits) for visits in visit_sets
    ]
    utilization_by_replication = []
    for visits in visit_sets:
        operating_time = max(
            visits[-1].finish_minute - visits[0].arrival_minute,
            1e-12,
        )
        utilization_by_replication.append(
            sum(visit.service_minutes for visit in visits) / operating_time
        )
    counts = [len(visits) for visits in visit_sets]
    return {
        "cashier": cashier_index + 1,
        "averageCustomers": mean(counts),
        "wait": descriptive_stats(wait_by_replication),
        "service": descriptive_stats(service_by_replication),
        "utilization": mean(utilization_by_replication),
        "queueing": _queue_estimate(visit_sets),
    }


def _before_after_summary(
    replications: list[Replication],
) -> list[dict]:
    results = []
    for cashier_index in range(3):
        before = _selected_visits(
            replications, 3, cashier_index, discard_warmup=False
        )
        after = _selected_visits(replications, 3, cashier_index)
        results.append({
            "cashier": cashier_index + 1,
            "before": {
                "wait": mean(visit.wait_minutes for visit in before),
                "service": mean(visit.service_minutes for visit in before),
            },
            "after": {
                "wait": mean(visit.wait_minutes for visit in after),
                "service": mean(visit.service_minutes for visit in after),
            },
        })
    return results


def build_results(experiment: dict) -> dict:
    replications = experiment["replications"]
    scenario_waits = {
        cashier_count: [
            _replication_wait(replication, cashier_count)
            for replication in replications
        ]
        for cashier_count in (3, 4)
    }
    scenarios = {
        cashier_count: descriptive_stats(waits)
        for cashier_count, waits in scenario_waits.items()
    }
    reductions = [
        wait_three - wait_four
        for wait_three, wait_four in zip(
            scenario_waits[3],
            scenario_waits[4],
        )
    ]
    reduction_stats = descriptive_stats(reductions)
    relative_reduction_pct = (
        reduction_stats["mean"] / scenarios[3]["mean"] * 100.0
        if scenarios[3]["mean"] > 0
        else 0.0
    )
    recommend_four = (
        experiment["converged"]
        and reduction_stats["low"] > 0
        and relative_reduction_pct >= MIN_WAIT_REDUCTION_PERCENT
    )

    baseline_cashiers = [
        _cashier_summary(replications, 3, index) for index in range(3)
    ]
    fastest = min(baseline_cashiers, key=lambda row: row["service"]["mean"])
    slowest = max(baseline_cashiers, key=lambda row: row["service"]["mean"])

    counts_by_replication = []
    for replication in replications:
        counts = {
            category: sum(
                customer.category == category
                for customer in replication.customers
            )
            for category in CATEGORY_ORDER
        }
        counts_by_replication.append({
            "replication": replication.number,
            "counts": counts,
            "total": sum(counts.values()),
        })

    users_by_type = []
    for category in CATEGORY_ORDER:
        counts = [
            row["counts"][category] for row in counts_by_replication
        ]
        minimum = min(counts)
        users_by_type.append({
            "category": category,
            "probability": CATEGORY_PROBABILITIES[category],
            "averagePerReplication": mean(counts),
            "minimum": minimum,
            "minimumReplications": [
                row["replication"]
                for row in counts_by_replication
                if row["counts"][category] == minimum
            ],
        })

    cashiers_four = [
        _cashier_summary(replications, 4, index) for index in range(4)
    ]
    convergence = experiment["convergenceHistory"]
    history = [
        {
            **item,
            "meanWaitThree": item["meanWaitThree"],
            "meanWaitFour": item["meanWaitFour"],
        }
        for item in convergence
    ]

    return {
        "seed": experiment["seed"],
        "replications": experiment["replicationsUsed"],
        "converged": experiment["converged"],
        "stability": {
            "batchSize": BATCH_SIZE,
            "relativeTolerancePct": STABILITY_RELATIVE_TOLERANCE * 100.0,
            "requiredChecks": STABILITY_REQUIRED_CHECKS,
            "history": history,
        },
        "scenarios": [
            {
                "cashiers": cashier_count,
                "label": f"{cashier_count} cajeros",
                "wait": scenarios[cashier_count],
            }
            for cashier_count in (3, 4)
        ],
        "decision": {
            "meanReductionMinutes": reduction_stats["mean"],
            "reduction": reduction_stats,
            "relativeReductionPct": relative_reduction_pct,
            "thresholdPct": MIN_WAIT_REDUCTION_PERCENT,
            "recommendFour": recommend_four,
        },
        "cashiersThree": baseline_cashiers,
        "cashiersFour": cashiers_four,
        "fastestCashier": {
            "cashier": fastest["cashier"],
            "serviceMean": fastest["service"]["mean"],
        },
        "slowestCashier": {
            "cashier": slowest["cashier"],
            "serviceMean": slowest["service"]["mean"],
        },
        "beforeAfter": _before_after_summary(replications),
        "usersByType": users_by_type,
        "replicationCounts": counts_by_replication[:30],
        "customersPerReplication": CUSTOMERS_PER_REPLICATION,
        "warmupCustomersPerCashier": WARMUP_CUSTOMERS_PER_CASHIER,
    }


def write_results(prefix: str, experiment: dict, data: dict) -> dict[str, str]:
    summary_path = Path(f"{prefix}_resumen.csv")
    replication_path = Path(f"{prefix}_replicas.csv")
    convergence_path = Path(f"{prefix}_convergencia.png")
    warmup_path = Path(f"{prefix}_antes_despues.png")

    with summary_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "registro", "escenario", "cajero", "tipo_usuario",
            "usuarios_promedio", "espera_promedio_min", "atencion_promedio_min",
            "utilizacion_pct", "lambda_por_min", "mu_por_min", "rho",
            "estable_mm1", "wq_mm1_min", "lq_mm1",
        ])
        for count, summaries in (
            (3, data["cashiersThree"]),
            (4, data["cashiersFour"]),
        ):
            for cashier in summaries:
                queueing = cashier["queueing"]
                writer.writerow([
                    "cajero",
                    f"{count} cajeros",
                    cashier["cashier"],
                    "",
                    f"{cashier['averageCustomers']:.4f}",
                    f"{cashier['wait']['mean']:.6f}",
                    f"{cashier['service']['mean']:.6f}",
                    f"{cashier['utilization'] * 100:.4f}",
                    f"{queueing['arrivalRate']:.8f}",
                    f"{queueing['serviceRate']:.8f}",
                    f"{queueing['rho']:.8f}",
                    "si" if queueing["stable"] else "no",
                    "" if queueing["wq"] is None else f"{queueing['wq']:.8f}",
                    "" if queueing["lq"] is None else f"{queueing['lq']:.8f}",
                ])
        for category in data["usersByType"]:
            writer.writerow([
                "tipo_usuario",
                "",
                "",
                category["category"],
                f"{category['averagePerReplication']:.4f}",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ])

    with replication_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "replica", "tipo_usuario", "usuarios", "espera_media_3_cajeros",
            "espera_media_4_cajeros",
        ])
        wait_three = [
            _replication_wait(replication, 3)
            for replication in experiment["replications"]
        ]
        wait_four = [
            _replication_wait(replication, 4)
            for replication in experiment["replications"]
        ]
        for replication in experiment["replications"]:
            counts = {
                category: sum(
                    customer.category == category
                    for customer in replication.customers
                )
                for category in CATEGORY_ORDER
            }
            index = replication.number - 1
            for category, count in counts.items():
                writer.writerow([
                    replication.number,
                    category,
                    count,
                    f"{wait_three[index]:.6f}",
                    f"{wait_four[index]:.6f}",
                ])

    history = data["stability"]["history"]
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.plot(
        [item["replications"] for item in history],
        [item["meanWaitThree"] for item in history],
        marker="o",
        label="3 cajeros",
    )
    axis.plot(
        [item["replications"] for item in history],
        [item["meanWaitFour"] for item in history],
        marker="o",
        label="4 cajeros",
    )
    axis.axvline(
        data["replications"],
        color="#b45309",
        linestyle="--",
        label=f"Réplicas utilizadas: {data['replications']}",
    )
    axis.set(
        title="Estabilidad del promedio acumulado de espera",
        xlabel="Réplicas acumuladas",
        ylabel="Espera promedio (min)",
    )
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(convergence_path, dpi=150)
    plt.close(figure)

    cashiers = data["beforeAfter"]
    x_values = list(range(1, len(cashiers) + 1))
    width = 0.35
    figure, axes = plt.subplots(1, 2, figsize=(11, 5))
    for axis, key, title, ylabel in (
        (axes[0], "wait", "Espera promedio", "Minutos"),
        (axes[1], "service", "Atención promedio", "Minutos"),
    ):
        before = [row["before"][key] for row in cashiers]
        after = [row["after"][key] for row in cashiers]
        axis.bar(
            [value - width / 2 for value in x_values],
            before,
            width,
            label="Antes: todos los usuarios",
            color="#94a3b8",
        )
        axis.bar(
            [value + width / 2 for value in x_values],
            after,
            width,
            label="Después: sin primeros 30",
            color="#0f766e",
        )
        axis.set_xticks(x_values, [f"Cajero {value}" for value in x_values])
        axis.set_title(title)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.25)
    axes[0].legend(fontsize=8)
    figure.suptitle("Efecto de eliminar el estado transitorio")
    figure.tight_layout()
    figure.savefig(warmup_path, dpi=150)
    plt.close(figure)

    return {
        "summaryCsv": summary_path.name,
        "replicationsCsv": replication_path.name,
        "convergenceChart": convergence_path.name,
        "warmupChart": warmup_path.name,
    }


def run_and_save(max_replicates: int, seed: int, prefix: str) -> dict:
    experiment = run_experiment(max_replicates, seed)
    data = build_results(experiment)
    data["files"] = write_results(prefix, experiment, data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulación del sistema de pago de parqueadero."
    )
    parser.add_argument("--max-replicas", type=int, default=200)
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--prefijo", default="resultados_parqueadero")
    args = parser.parse_args()
    data = run_and_save(args.max_replicas, args.semilla, args.prefijo)
    print(f"Réplicas utilizadas: {data['replications']}")
    print(f"Estabilidad alcanzada: {'sí' if data['converged'] else 'no'}")
    for scenario in data["scenarios"]:
        print(
            f"{scenario['label']}: espera media "
            f"{scenario['wait']['mean']:.3f} min"
        )
    print(
        "Cajero con menor atención promedio: "
        f"{data['fastestCashier']['cashier']} "
        f"({data['fastestCashier']['serviceMean']:.3f} min)."
    )
    print(
        "Cajero con mayor atención promedio: "
        f"{data['slowestCashier']['cashier']} "
        f"({data['slowestCashier']['serviceMean']:.3f} min)."
    )
    print(f"Archivos generados: {data['files']}")


if __name__ == "__main__":
    main()
