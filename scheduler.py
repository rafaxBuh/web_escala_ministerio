"""
Algoritmo de geração de escala mensal.
Adaptado do app desktop para usar period_id e ministry_id.

Critérios de seleção da dupla (em ordem de prioridade):
1. Não repetir ninguém da semana anterior
2. Minimizar uso acumulado (rodízio justo)
3. Não repetir a mesma dupla
4. Minimizar diferença de uso entre os dois da dupla
"""
from itertools import combinations
from collections import defaultdict


def generate_period_schedule(period_id: int, ministry_id: int, total_weeks: int = 4):
    """
    Gera e salva a escala de um período.
    Retorna lista de dicts com {week, member1_id, member2_id, member1, member2}.
    Lança ValueError se não houver voluntários suficientes em alguma semana.
    """
    from models import (
        get_availability_for_period_week,
        save_schedule,
        clear_period_schedule,
        get_pair_restrictions_set,
        get_recruta_companions_dict,
    )

    usage_count = defaultdict(int)
    pair_count = defaultdict(int)
    last_week_members: set = set()
    restrictions = get_pair_restrictions_set(ministry_id)
    # {recruta_id: set(companion_ids)} — só recrutas com acompanhantes definidos
    recruta_companions = get_recruta_companions_dict(ministry_id)

    clear_period_schedule(period_id)

    chosen_schedule = []

    try:
        for week in range(1, total_weeks + 1):
            availability = get_availability_for_period_week(period_id, week)

            available_members = [
                {"id": row["id"], "name": row["name"], "role": row["role"]}
                for row in availability
                if row["available"] == 1
            ]

            if len(available_members) < 2:
                raise ValueError(
                    f"Semana {week}: apenas {len(available_members)} voluntário(s) "
                    f"disponível(is). São necessários pelo menos 2."
                )

            def _pair_allowed(a, b):
                key = tuple(sorted((a["id"], b["id"])))
                if key in restrictions:
                    return False
                # Recruta só pode servir com acompanhante definido (se houver lista)
                if a["role"] == "recruta" and a["id"] in recruta_companions:
                    if b["id"] not in recruta_companions[a["id"]]:
                        return False
                if b["role"] == "recruta" and b["id"] in recruta_companions:
                    if a["id"] not in recruta_companions[b["id"]]:
                        return False
                return True

            possible_pairs = [
                pair
                for pair in combinations(available_members, 2)
                if _pair_allowed(pair[0], pair[1])
            ]

            if not possible_pairs:
                raise ValueError(
                    f"Semana {week}: nenhuma dupla válida — verifique restrições e "
                    f"disponibilidades."
                )

            def score(pair):
                id1, id2 = pair[0]["id"], pair[1]["id"]
                ids = {id1, id2}
                repeated_from_last_week = len(ids & last_week_members)
                total_usage = usage_count[id1] + usage_count[id2]
                pair_key = tuple(sorted((id1, id2)))
                repeated_pair = pair_count[pair_key]
                usage_difference = abs(usage_count[id1] - usage_count[id2])
                return (
                    repeated_from_last_week,
                    total_usage,
                    repeated_pair,
                    usage_difference,
                    pair[0]["name"],
                    pair[1]["name"],
                )

            possible_pairs.sort(key=score)

            # Preferir dupla sem ninguém da semana anterior
            best_pair = None
            for pair in possible_pairs:
                if len({pair[0]["id"], pair[1]["id"]} & last_week_members) == 0:
                    best_pair = pair
                    break

            if best_pair is None:
                best_pair = possible_pairs[0]

            m1, m2 = best_pair
            id1, id2 = m1["id"], m2["id"]
            pair_key = tuple(sorted((id1, id2)))

            usage_count[id1] += 1
            usage_count[id2] += 1
            pair_count[pair_key] += 1
            last_week_members = {id1, id2}

            save_schedule(period_id, week, id1, id2)

            chosen_schedule.append({
                "week": week,
                "member1_id": id1,
                "member2_id": id2,
                "member1": m1["name"],
                "member2": m2["name"],
            })
    except ValueError:
        clear_period_schedule(period_id)
        raise

    return chosen_schedule
