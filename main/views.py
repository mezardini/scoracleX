import numpy as np
from functools import lru_cache
from django.db import transaction
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import aiohttp
import asyncio
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views import View
from django.http import HttpResponse, JsonResponse
from .models import Fixture
from bs4 import BeautifulSoup
from uuid import uuid4
import requests
from scipy.stats import poisson
import math
import json
import ast
from .utils import fetch_data, calculate_poisson_probs, predict_match_result, get_top_probable_scorelines

# Create your views here.


def home(request):
    today = timezone.now().date()
    fixtures = Fixture.objects.filter(date__date=today)
    return render(request, 'home_view.html', {'fixtures': fixtures})

def fixture_details(request, fixture_id):
    fixture = get_object_or_404(Fixture, fixture_id=fixture_id)
    
    scorelines = []
    try:
        # Some predicted scorelines may be stored as string representations of lists or tuples
        parsed = json.loads(fixture.predicted_scorelines)
        if isinstance(parsed, str):
            scorelines = ast.literal_eval(parsed)
        else:
            scorelines = parsed
    except Exception:
        pass
        
    return render(request, 'fixture-details.html', {
        'fixture': fixture,
        'scorelines': scorelines
    })


class LeaguePredictionX(View):
    league_data = {}  # Class variable to store league data

    def get(self, request, league, save_to_db=False):
        """
        Modified to accept save_to_db parameter for internal calls
        """
        if not league:
            return HttpResponse({'error': 'League parameter is required.'})

        league = league.strip()

        urlavgtable = f'https://www.soccerstats.com/table.asp?league={league}&tid=d'
        urlfixture = f'https://www.soccerstats.com/latest.asp?league={league}'

        try:
            # Fetch league table data
            response = requests.get(urlavgtable, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            table = soup.find("table", {"id": "btable"})

            if not table:
                return HttpResponse({'error': f'Could not find table for league {league}'})

            header = table.find_all("th")
            header = [h.text.strip() for h in header]
            rows = table.find_all("tr")[1:]
            self.league_data[league] = {'header': header, 'rows': []}

            for row in rows[1:]:
                cols = row.find_all('td')
                cols = [col.text.strip() for col in cols]
                if cols:
                    self.league_data[league]['rows'].append(cols)

            # Fetch fixtures
            res = requests.get(urlfixture, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'html.parser')

            odd_rowsA = soup.find_all(
                'tr', {'height': '50', 'bgcolor': '#fff5e6'})
            odd_rowsB = soup.find_all(
                'tr', {'height': '42', 'bgcolor': '#fff5e6'})
            cols = []

            if odd_rowsA:
                for row in odd_rowsA:
                    teams_td = row.find_all('td')[1]
                    br_tag = teams_td.find('br')

                    if br_tag:
                        team1 = br_tag.previous_sibling.strip() if br_tag.previous_sibling else None
                        team2 = br_tag.next_sibling.strip() if br_tag.next_sibling else None
                        if team1 and team2:
                            cols.append([team1, team2])
                    else:
                        team_links = teams_td.find_all('a')
                        if len(team_links) == 2:
                            team1 = team_links[0].text.strip()
                            team2 = team_links[1].text.strip()
                            cols.append([team1, team2])

            elif odd_rowsB:
                for row in odd_rowsB:
                    teams_td = row.find_all('td')[1]
                    team_links = teams_td.find_all('a')
                    if len(team_links) == 2:
                        team1 = team_links[0].text.strip()
                        team2 = team_links[1].text.strip()
                        cols.append([team1, team2])

            output = cols
            teams = [row[0] for row in self.league_data[league]['rows'] if row]

            # Get averages
            stats_table = soup.find(
                "table", style=lambda value: value and "margin-left:14px" in value)
            Home_avg = 100.0
            Away_avg = 100.0

            if stats_table:
                b_tags = stats_table.find_all("b")
                if len(b_tags) >= 9:
                    try:
                        Home_avg = float(b_tags[8].text)
                    except ValueError:
                        pass
                if len(b_tags) >= 11:
                    try:
                        Away_avg = float(b_tags[10].text)
                    except ValueError:
                        pass

            H3 = Home_avg
            A3 = Away_avg
            predictions_list = []

            for i in output:
                first_item = i[0]
                second_item = i[1]

                row_list = None
                row_listaway = None

                for idx, team_row in enumerate(self.league_data[league]['rows']):
                    if team_row and team_row[0] == first_item:
                        row_list = team_row
                    if team_row and team_row[0] == second_item:
                        row_listaway = team_row

                if not row_list or not row_listaway:
                    continue

                try:
                    H1 = float(row_list[6]) / H3 if H3 != 0 else 0
                    H2 = float(row_listaway[11]) / H3 if H3 != 0 else 0
                    Home_goal = H1 * H2 * H3

                    A1 = float(row_list[7]) / A3 if A3 != 0 else 0
                    A2 = float(row_listaway[10]) / A3 if A3 != 0 else 0
                    Away_goal = A1 * A2 * A3
                except (IndexError, ValueError):
                    continue

                twomatch_goals_probability = (
                    1 - poisson.cdf(k=2, mu=(Home_goal + Away_goal))) * 100
                threematch_goals_probability = (
                    1 - poisson.cdf(k=3, mu=(Home_goal + Away_goal))) * 100

                lambda_home = Home_goal
                lambda_away = Away_goal

                score_probs = [[poisson.pmf(i, team_avg) for i in range(0, 10)]
                               for team_avg in [lambda_home, lambda_away]]
                outcomes = [[i, j] for i in range(0, 10) for j in range(0, 10)]
                probs = [score_probs[0][i] * score_probs[1][j]
                         for i, j in outcomes]
                most_likely_outcome = outcomes[probs.index(max(probs))]
                most_likely_prob_percent = max(probs) * 100

                probable_scorelines = get_top_probable_scorelines(
                    lambda_home, lambda_away, n=5)

                prediction_data = {
                    'fixture': f"{first_item} vs {second_item}",
                    'predicted_score': f"{most_likely_outcome[0]} - {most_likely_outcome[1]}",
                    'home_team': first_item,
                    'away_team': second_item,
                    'home_goals_predicted': round(Home_goal, 2),
                    'away_goals_predicted': round(Away_goal, 2),
                    'over_2_5_probability': round(threematch_goals_probability, 2),
                    'over_1_5_probability': round(twomatch_goals_probability, 2),
                    'league': league,
                    'top_scorelines': probable_scorelines,
                    'most_likely_probability': round(most_likely_prob_percent, 2)
                }
                predictions_list.append(prediction_data)

            # Save to database if requested using bulk_create
            if save_to_db and predictions_list:
                self.save_predictions_bulk(league, predictions_list)

            return HttpResponse(predictions_list)

        except Exception as e:
            return HttpResponse({'error': str(e)})

    # def save_predictions_bulk(self, league, predictions_list):
    #     """
    #     Save predictions using bulk_create for better performance
    #     """
    #     today = timezone.now().date()

    #     # Prepare Prediction objects for bulk creation
    #     prediction_objects = [
    #         Prediction(
    #             content={
    #                 'league': league,
    #                 'fixture': pred['fixture'],
    #                 'home_team': pred['home_team'],
    #                 'away_team': pred['away_team'],
    #                 'predicted_score': pred['predicted_score'],
    #                 'home_goals_predicted': pred['home_goals_predicted'],
    #                 'away_goals_predicted': pred['away_goals_predicted'],
    #                 'over_2_5_probability': pred['over_2_5_probability'],
    #                 'over_1_5_probability': pred['over_1_5_probability'],
    #                 'top_scorelines': pred['top_scorelines'],
    #                 'most_likely_probability': pred['most_likely_probability']
    #             },
    #             date=today
    #         )
    #         for pred in predictions_list
    #     ]

    #     # Bulk create all predictions for this league
    #     with transaction.atomic():
    #         Prediction.objects.bulk_create(prediction_objects, batch_size=100)

    #     print(
    #         f"✓ Bulk created {len(prediction_objects)} predictions for {league}")


# Pre-calculate Poisson PMF values (optimization)
POISSON_CACHE = {}


def get_poisson_pmf(k, mu):
    """Cached Poisson PMF calculation"""
    key = (k, round(mu, 2))
    if key not in POISSON_CACHE:
        POISSON_CACHE[key] = poisson.pmf(k, mu)
    return POISSON_CACHE[key]


@lru_cache(maxsize=128)
def calculate_scoreline_probabilities(lambda_home, lambda_away):
    """Cached scoreline calculation - expensive operation"""
    # Vectorized calculation instead of nested loops
    home_goals = np.arange(0, 10)
    away_goals = np.arange(0, 10)

    home_probs = poisson.pmf(home_goals, lambda_home)
    away_probs = poisson.pmf(away_goals, lambda_away)

    # Outer product for all combinations
    prob_matrix = np.outer(home_probs, away_probs)

    # Get top 5 outcomes
    flat_indices = np.argsort(prob_matrix.ravel())[-5:][::-1]
    outcomes = [(idx // 10, idx % 10) for idx in flat_indices]
    probs = [prob_matrix[i, j] * 100 for i, j in outcomes]

    return list(zip(outcomes, probs))


async def fetch_url(session, url):
    """Async HTTP fetch"""
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
        return await response.text()


async def get_league_data_async(session, league):
    """Fetch both URLs concurrently"""
    urlavgtable = f'https://www.soccerstats.com/table.asp?league={league}&tid=d'
    urlfixture = f'https://www.soccerstats.com/latest.asp?league={league}'

    table_task = fetch_url(session, urlavgtable)
    fixture_task = fetch_url(session, urlfixture)

    table_html, fixture_html = await asyncio.gather(table_task, fixture_task)
    return table_html, fixture_html


def parse_league_table(html):
    """Parse league table - CPU bound, run in thread"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "btable"})
    if not table:
        return None, None

    header = [h.text.strip() for h in table.find_all("th")]
    rows = []
    for row in table.find_all("tr")[2:]:  # Skip header rows
        cols = row.find_all('td')
        if cols:
            rows.append([col.text.strip() for col in cols])

    return header, rows


def parse_fixtures(html):
    """Parse fixtures - CPU bound"""
    soup = BeautifulSoup(html, 'html.parser')
    fixtures = []

    # Try both row types
    for selector in [
        {'height': '50', 'bgcolor': '#fff5e6'},
        {'height': '42', 'bgcolor': '#fff5e6'}
    ]:
        rows = soup.find_all('tr', selector)
        for row in rows:
            teams_td = row.find_all('td')
            if len(teams_td) < 2:
                continue

            teams_td = teams_td[1]
            br_tag = teams_td.find('br')

            if br_tag:
                team1 = br_tag.previous_sibling.strip() if br_tag.previous_sibling else None
                team2 = br_tag.next_sibling.strip() if br_tag.next_sibling else None
            else:
                team_links = teams_td.find_all('a')
                if len(team_links) == 2:
                    team1 = team_links[0].text.strip()
                    team2 = team_links[1].text.strip()
                else:
                    continue

            if team1 and team2:
                fixtures.append([team1, team2])

        if fixtures:
            break

    # Get averages
    table = soup.find("table", style=lambda x: x and "margin-left:14px" in x)
    home_avg, away_avg = 100.0, 100.0

    if table:
        b_tags = table.find_all("b")
        if len(b_tags) >= 9:
            try:
                home_avg = float(b_tags[8].text)
            except ValueError:
                pass
        if len(b_tags) >= 11:
            try:
                away_avg = float(b_tags[10].text)
            except ValueError:
                pass

    return fixtures, home_avg, away_avg


def create_prediction(fixture, league, league_data, teams, H3, A3):
    """Create single prediction and save immediately"""
    first_item, second_item = fixture

    if first_item not in teams or second_item not in teams:
        return None

    row_list = league_data['rows'][teams.index(first_item)]
    row_listaway = league_data['rows'][teams.index(second_item)]

    # Calculate goals (vectorized)
    H1 = float(row_list[6]) / H3
    H2 = float(row_listaway[11]) / H3
    Home_goal = H1 * H2 * H3

    A1 = float(row_list[7]) / A3
    A2 = float(row_listaway[10]) / A3
    Away_goal = A1 * A2 * A3

    # Over goals probabilities
    total_goals = Home_goal + Away_goal
    twomatch_goals_probability = (1 - poisson.cdf(2, total_goals)) * 100
    threematch_goals_probability = (1 - poisson.cdf(3, total_goals)) * 100

    # Get scorelines (cached calculation)
    probable_scorelines = calculate_scoreline_probabilities(
        Home_goal, Away_goal)
    most_likely_outcome, most_likely_prob = probable_scorelines[0]

    # Save to database immediately
    try:
        with transaction.atomic():
            Fixture.objects.update_or_create(
                home_team=first_item,
                away_team=second_item,
                league=league,  # Now properly passed
                defaults={
                    'fixture_id': str(uuid4())[:16],
                    'home_team_score': most_likely_outcome[0],
                    'away_team_score': most_likely_outcome[1],
                    'date': timezone.now(),
                    'predicted_scorelines': str(probable_scorelines),
                    'over_3_goals_probability': threematch_goals_probability,
                    'over_2_goals_probability': twomatch_goals_probability,
                }
            )
    except Exception as e:
        print(f"DB Error for {first_item} vs {second_item}: {e}")
        return None

    return {
        'Fixture': f"{first_item} {most_likely_outcome[0]} vs {second_item} {most_likely_outcome[1]}",
        'Home_Team': first_item,
        'Away_Team': second_item,
        'Home_team_score': most_likely_outcome[0],
        'Away_team_score': most_likely_outcome[1],
        'Over_2_5_Goals_Probability': f"{threematch_goals_probability:.2f}%",
        'Over_1_5_Goals_Probability': f"{twomatch_goals_probability:.2f}%",
        'League': league,
        'Top_Scorelines': str(probable_scorelines),
    }

async def process_league(league):
    """Process single league with immediate saves"""
    async with aiohttp.ClientSession() as session:
        try:
            table_html, fixture_html = await get_league_data_async(session, league)

            # Parse in thread pool to not block async
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as pool:
                header_rows = await loop.run_in_executor(pool, parse_league_table, table_html)
                fixtures_data = await loop.run_in_executor(pool, parse_fixtures, fixture_html)

            header, rows = header_rows
            fixtures, H3, A3 = fixtures_data

            if not rows or not fixtures:
                return {'league': league, 'status': 'no_data', 'predictions': 0}

            league_data = {'header': header, 'rows': rows}
            teams = [row[0] for row in rows]

            predictions = []
            for fixture in fixtures:
                pred = create_prediction(fixture, league_data, teams, H3, A3)
                if pred:
                    predictions.append(pred)

            return {
                'league': league,
                'status': 'success',
                'predictions': len(predictions),
                'data': predictions
            }

        except Exception as e:
            return {'league': league, 'status': 'error', 'error': str(e)}


class AllLeaguesPrediction(View):
    leagues = [
        'spain', 'england', 'france', 'germany', 'italy', 'germany2', 'norway',
        'norway2', 'iceland', 'sweden', 'sweden2', 'portugal', 'netherlands',
        'netherlands2', 'russia', 'belgium', 'turkey', 'ukraine',
        'czechrepublic', 'austria', 'switzerland', 'greece', 'scotland', 'croatia',
        'denmark', 'poland', 'spain2', 'england2', 'italy2', 'france2', 'armenia',
        'belarus'
    ]

    async def get(self, request):
        """Process all leagues concurrently with immediate DB saves"""
        # Process leagues in batches to avoid overwhelming the server
        batch_size = 5
        all_results = []

        for i in range(0, len(self.leagues), batch_size):
            batch = self.leagues[i:i + batch_size]
            tasks = [process_league(league) for league in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            all_results.extend(batch_results)

        # Compile summary
        successful = [r for r in all_results if isinstance(
            r, dict) and r.get('status') == 'success']
        failed = [r for r in all_results if isinstance(
            r, dict) and r.get('status') == 'error']

        total_predictions = sum(r.get('predictions', 0) for r in successful)

        return JsonResponse({
            'summary': {
                'total_leagues': len(self.leagues),
                'successful': len(successful),
                'failed': len(failed),
                'total_predictions': total_predictions,
            },
            'results': all_results
        }, safe=False)
