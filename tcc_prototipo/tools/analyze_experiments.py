import json
from collections import Counter
from pathlib import Path

def load_experiments(experiments_path: Path) -> list[dict]:
    experiments = []
    
    for file_path in sorted(
        experiments_path.glob("experiment_*.json")
    ):
        try:
            data = json.loads(
                file_path.read_text(
                    encoding="utf-8"
                )
            )
            
            experiments.append(data)
        
        except (json.JSONDecodeError, OSError) as error:
            print(
                f"Não foi possível ler "
                f"{file_path.name}: {error}"
            )
    
    return experiments

def analyze_experiments(
    experiments: list[dict]
) -> dict:

    if not experiments:
        return {
            "total_experiments": 0,
            "successful_experiments": 0,
            "success_rate": 0,
            "first_attempt_successes": 0,
            "first_attempt_success_rate": 0,
            "average_attempts": 0,
            "max_attempts": 0,
            "error_frequency": {},
        }

    successful_experiments = sum(
        experiment.get("success", False)
        for experiment in experiments
    )

    first_attempt_successes = 0
    total_attempts = 0
    max_attempts = 0

    error_counter = Counter()

    for experiment in experiments:

        attempts = experiment.get(
            "attempts",
            []
        )

        attempt_count = len(attempts)

        total_attempts += attempt_count

        max_attempts = max(
            max_attempts,
            attempt_count
        )

        if attempts:
            if attempts[0].get("valid", False):
                first_attempt_successes += 1

        for attempt in attempts:

            if attempt.get("valid", False):
                continue

            for error in attempt.get(
                "errors",
                []
            ):
                error_counter[error] += 1

    total_experiments = len(experiments)

    return {
        "total_experiments": total_experiments,

        "successful_experiments":
            successful_experiments,

        "success_rate":
            successful_experiments
            / total_experiments
            * 100,

        "first_attempt_successes":
            first_attempt_successes,

        "first_attempt_success_rate":
            first_attempt_successes
            / total_experiments
            * 100,

        "average_attempts":
            total_attempts
            / total_experiments,

        "max_attempts":
            max_attempts,

        "error_frequency":
            dict(error_counter.most_common()),
    }

def print_analysis(
    analysis: dict
) -> None:

    print("\n" + "=" * 50)
    print("ANÁLISE DOS EXPERIMENTOS")
    print("=" * 50)

    print(
        f"\nTotal de experimentos: "
        f"{analysis['total_experiments']}"
    )

    print(
        f"Experimentos concluídos com sucesso: "
        f"{analysis['successful_experiments']}"
    )

    print(
        f"Taxa de sucesso: "
        f"{analysis['success_rate']:.2f}%"
    )

    print(
        f"Sucessos na primeira tentativa: "
        f"{analysis['first_attempt_successes']}"
    )

    print(
        f"Taxa de sucesso na primeira tentativa: "
        f"{analysis['first_attempt_success_rate']:.2f}%"
    )

    print(
        f"Média de tentativas: "
        f"{analysis['average_attempts']:.2f}"
    )

    print(
        f"Maior número de tentativas: "
        f"{analysis['max_attempts']}"
    )

    print("\nErros mais frequentes:")

    if not analysis["error_frequency"]:
        print("Nenhum erro registrado.")

    else:
        for error, count in analysis[
            "error_frequency"
        ].items():

            print(
                f"- {count}x: {error}"
            )

    print("\n" + "=" * 50)

def main() -> int:

    project_root = (
        Path(__file__).resolve().parent.parent
    )

    experiments_path = (
        project_root / "experiments"
    )

    if not experiments_path.exists():

        print(
            "A pasta de experimentos não foi encontrada:"
        )

        print(experiments_path)

        return 1

    experiments = load_experiments(
        experiments_path
    )

    if not experiments:

        print(
            "Nenhum experimento encontrado."
        )

        return 1

    analysis = analyze_experiments(
        experiments
    )

    print_analysis(
        analysis
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())