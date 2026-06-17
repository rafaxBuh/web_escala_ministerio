"""
Algoritmo de geração de escala mensal.

Critérios de seleção da dupla regular (em ordem de prioridade):
1. Não repetir ninguém da semana anterior
2. Minimizar uso acumulado (rodízio justo)
3. Não repetir a mesma dupla
4. Minimizar diferença de uso entre os dois da dupla

Recrutas nunca fazem parte da dupla principal — são adicionados como
terceiro membro quando um de seus acompanhantes está na dupla.
"""
from itertools import combinations
from collections import defaultdict


def generate_period_schedule(period_id: int, ministry_id: int, total_weeks: int = 4):
    """
    Gera e salva a escala de um período.
    Retorna lista de dicts com {week, member1_id, member2_id, member3_id, member1, member2, member3}.
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
    recruta_companions = get_recruta_companions_dict(ministry_id)

    clear_period_schedule(period_id)

    chosen_schedule = []

    try:
        for week in range(1, total_weeks + 1):
            availability = get_availability_for_period_week(period_id, week)

            all_available = [
                {"id": row["id"], "name": row["name"], "role": row["role"]}
                for row in availability
                if row["available"] == 1
            ]

            regular_members = [m for m in all_available if m["role"] != "recruta"]
            recruta_members = [m for m in all_available if m["role"] == "recruta"]

            if len(regular_members) < 2:
                raise ValueError(
                    f"Semana {week}: apenas {len(regular_members)} voluntário(s) regular(es) "
                    f"disponível(is). São necessários pelo menos 2."
                )

            def _pair_allowed(a, b):
                return tuple(sorted((a["id"], b["id"]))) not in restrictions

            possible_pairs = [
                pair
                for pair in combinations(regular_members, 2)
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

            best_pair = None
            for pair in possible_pairs:
                if len({pair[0]["id"], pair[1]["id"]} & last_week_members) == 0:
                    best_pair = pair
                    break
            if best_pair is None:
                best_pair = possible_pairs[0]

            m1, m2 = best_pair
            id1, id2 = m1["id"], m2["id"]
            pair_ids = {id1, id2}
            pair_key = tuple(sorted((id1, id2)))

            usage_count[id1] += 1
            usage_count[id2] += 1
            pair_count[pair_key] += 1
            last_week_members = {id1, id2}

            # Adiciona recruta como 3º membro se um acompanhante está na dupla
            member3 = None
            for recruta in recruta_members:
                companions = recruta_companions.get(recruta["id"], set())
                if companions and pair_ids & companions:
                    member3 = recruta
                    break

            member3_id = None
            if member3:
                member3_id = member3["id"]
                usage_count[member3_id] += 1

            save_schedule(period_id, week, id1, id2, member3_id)

            chosen_schedule.append({
                "week": week,
                "member1_id": id1,
                "member2_id": id2,
                "member3_id": member3_id,
                "member1": m1["name"],
                "member2": m2["name"],
                "member3": member3["name"] if member3 else None,
            })
    except ValueError:
        clear_period_schedule(period_id)
        raise

    return chosen_schedule
