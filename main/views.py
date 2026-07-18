from django.db.models import Case, When, Value, IntegerField
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from functools import lru_cache
from django.db import transaction
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
# import aiohttp
import asyncio
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.http import HttpResponse, JsonResponse
from .models import Fixture
from .forms import LoginForm, RegisterForm
from bs4 import BeautifulSoup
from uuid import uuid4
import requests
from scipy.stats import poisson
import math
import json
import ast
from .utils import fetch_data, calculate_poisson_probs, predict_match_result, get_top_probable_scorelines, analyze_fixture

# Create your views here.
from itertools import groupby

from django.db.models import Case, When, Value, IntegerField


GUEST_FIXTURE_LIMIT = 10


def get_sorted_fixtures(date_value):
    """
    Helper to filter and rank fixtures by UEFA coefficient/Priority
    """
    priority_map = Case(
        When(league__iexact='england', then=Value(1)),
        When(league__iexact='spain', then=Value(2)),
        When(league__iexact='germany', then=Value(3)),
        When(league__iexact='italy', then=Value(4)),
        When(league__iexact='france', then=Value(5)),
        default=Value(100),
        output_field=IntegerField(),
    )

    return Fixture.objects.filter(date__date=date_value).annotate(
        priority=priority_map
    ).order_by('priority', 'league', 'home_team')

# --- Updated Home View ---


LEAGUE_DISPLAY_NAMES = {
    'spain':          'Spain • La Liga',
    'spain2':         'Spain • Segunda División',
    'england':        'England • Premier League',
    'england2':       'England • Championship',
    'france':         'France • Ligue 1',
    'france2':        'France • Ligue 2',
    'germany':        'Germany • Bundesliga',
    'germany2':       'Germany • 2. Bundesliga',
    'italy':          'Italy • Serie A',
    'italy2':         'Italy • Serie B',
    'portugal':       'Portugal • Primeira Liga',
    'netherlands':    'Netherlands • Eredivisie',
    'netherlands2':   'Netherlands • Eerste Divisie',
    'belgium':        'Belgium • First Division A',
    'turkey':         'Turkey • Süper Lig',
    'greece':         'Greece • Super League',
    'scotland':       'Scotland • Premiership',
    'russia':         'Russia • Premier League',
    'ukraine':        'Ukraine • Premier League',
    'czechrepublic':  'Czech Republic • First League',
    'austria':        'Austria • Bundesliga',
    'switzerland':    'Switzerland • Super League',
    'croatia':        'Croatia • Prva HNL',
    'denmark':        'Denmark • Superliga',
    'poland':         'Poland • Ekstraklasa',
    'norway':         'Norway • Eliteserien',
    'norway2':        'Norway • First Division',
    'sweden':         'Sweden • Allsvenskan',
    'sweden2':        'Sweden • Division 2',
    'iceland':        'Iceland • Úrvalsdeild',
    'armenia':        'Armenia • Premier League',
    'belarus':        'Belarus • Premier League',
    'brazil':         'Brazil • Série A',
    'bulgaria':       'Bulgaria • First League',
    'cyprus':         'Cyprus • First Division',
    'finland':        'Finland • Veikkausliiga',
}


def home(request):
    today = timezone.now().date()
    fixtures = get_unique_fixtures(get_sorted_fixtures(today))
    is_limited = not request.user.is_authenticated
    if is_limited:
        fixtures = fixtures[:GUEST_FIXTURE_LIMIT]

    # Group fixtures by league, preserving sort order
    grouped = []
    for league_key, group in groupby(fixtures, key=lambda f: f.league):
        grouped.append({
            'league_key':  league_key,
            'league_name': LEAGUE_DISPLAY_NAMES.get(league_key, league_key.replace('_', ' ').title()),
            'fixtures':    list(group),
        })

    return render(request, 'home_view.html', {
        'grouped_fixtures': grouped,
        'guest_fixture_limit': GUEST_FIXTURE_LIMIT,
        'is_guest_limited': is_limited,
    })


def get_unique_fixtures(fixtures):
    unique_fixtures = []
    seen = set()

    for fixture in fixtures:
        key = (
            fixture.league,
            fixture.home_team.strip().lower(),
            fixture.away_team.strip().lower(),
            fixture.date.date(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_fixtures.append(fixture)

    return unique_fixtures


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def register_user(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(signup_ip=get_client_ip(request))
            login(request, user)
            messages.success(request, 'Your account is ready.')
            return redirect('home')
    else:
        form = RegisterForm()

    return render(request, 'registration/register.html', {'form': form})


def login_user(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.user
            user.last_login_ip = get_client_ip(request)
            user.save(update_fields=['last_login_ip', 'updated_at'])
            login(request, user)
            messages.success(request, 'Welcome back.')
            return redirect(request.GET.get('next') or 'home')
    else:
        form = LoginForm(request)

    return render(request, 'registration/login.html', {'form': form})


def logout_user(request):
    logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('home')


def bad_request(request, exception):
    return render(request, '400.html', status=400)


def permission_denied(request, exception):
    return render(request, '403.html', status=403)


def page_not_found(request, exception):
    return render(request, '404.html', status=404)


def server_error(request):
    return render(request, '500.html', status=500)

# --- Updated API View ---


def get_fixtures_by_date(request):
    selected_date = request.GET.get('date')
    if selected_date:
        fixtures = get_unique_fixtures(get_sorted_fixtures(selected_date))
        if not request.user.is_authenticated:
            fixtures = fixtures[:GUEST_FIXTURE_LIMIT]
        return JsonResponse([
            {
                'fixture_id': fixture.fixture_id,
                'home_team': fixture.home_team,
                'away_team': fixture.away_team,
                'home_team_score': fixture.home_team_score,
                'away_team_score': fixture.away_team_score,
                'league': fixture.league,
                'over_2_goals_probability': fixture.over_2_goals_probability,
                'over_3_goals_probability': fixture.over_3_goals_probability,
                'over_1_5_probability': fixture.over_2_goals_probability,
                'over_2_5_probability': fixture.over_3_goals_probability,
                'home_win_probability': fixture.home_win_probability,
                'away_win_probability': fixture.away_win_probability,
                'draw_probability': fixture.draw_probability,
            }
            for fixture in fixtures
        ], safe=False)
    return JsonResponse({'error': 'No date'}, status=400)


def fixture_details(request, fixture_id):
    fixture = get_object_or_404(Fixture, fixture_id=fixture_id)

    print("RAW:", repr(fixture.predicted_scorelines))

    try:
        scorelines = ast.literal_eval(fixture.predicted_scorelines)
        print("PARSED:", scorelines)
    except (ValueError, SyntaxError) as e:
        print("PARSE ERROR:", e)
        scorelines = []

    return render(request, 'fixture-details.html', {
        'fixture': fixture,
        'scorelines': scorelines,
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

                # 2. Call the new function to get overall win/draw percentages
                match_odds = analyze_fixture(lambda_home, lambda_away)

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
                    'most_likely_probability': round(most_likely_prob_percent, 2),
                    'home_win_probability': match_odds['home_win'],
                    'away_win_probability': match_odds['away_win'],
                    'draw_probability': match_odds['draw']
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


def get_league_prediction(request, league):
    league_data = {}
    if not league:
        return []  # Return empty list, not HttpResponse

    base_url = 'https://www.soccerstats.com/'
    urlavgtable = f'https://www.soccerstats.com/table.asp?league={league}&tid=d'
    urlfixture = f'https://www.soccerstats.com/latest.asp?league={league}'

    try:
        response = requests.get(urlavgtable, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", {"id": "btable"})

        if not table:
            print(f"[{league}] No stats table found")
            return []

        header = [h.text.strip() for h in table.find_all("th")]
        rows = table.find_all("tr")[1:]
        league_data[league] = {'header': header, 'rows': []}

        for row in rows[1:]:
            cols = [col.text.strip() for col in row.find_all('td')]
            league_data[league]['rows'].append(cols)

        res = requests.get(urlfixture, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        odd_rowsA = soup.find_all('tr', {'height': '50', 'bgcolor': '#fff5e6'})
        odd_rowsB = soup.find_all('tr', {'height': '42', 'bgcolor': '#fff5e6'})
        cols = []

        if odd_rowsA:
            for row in odd_rowsA:
                teams_td = row.find_all('td')[1]
                br_tag = teams_td.find('br')
                if br_tag:
                    team1 = br_tag.previous_sibling.strip() if br_tag.previous_sibling else ''
                    team2 = br_tag.next_sibling.strip() if br_tag.next_sibling else ''
                    if team1 and team2:
                        cols.append([team1, team2])
                else:
                    team_links = teams_td.find_all('a')
                    if len(team_links) == 2:
                        cols.append([team_links[0].text.strip(),
                                    team_links[1].text.strip()])
        elif odd_rowsB:
            for row in odd_rowsB:
                teams_td = row.find_all('td')[1]
                team_links = teams_td.find_all('a')
                if len(team_links) == 2:
                    cols.append([team_links[0].text.strip(),
                                team_links[1].text.strip()])

        if not cols:
            print(f"[{league}] No fixtures found")
            return []

        teams = [row[0] for row in league_data[league]['rows']]

        b_tags = soup.find_all('b')
        stats_table = soup.find(
            "table", style="margin-left:14px;margin-riht:14px;border:1px solid #aaaaaa;border-radius:12px;overflow:hidden;")

        Home_avg = 1.0
        Away_avg = 1.0
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

        for i in cols:
            first_item, second_item = i[0], i[1]

            # Skip if either team not found in stats table
            if first_item not in teams or second_item not in teams:
                print(
                    f"[{league}] Skipping {first_item} vs {second_item} — team not in stats table")
                continue

            row_list = league_data[league]['rows'][teams.index(first_item)]
            row_listaway = league_data[league]['rows'][teams.index(
                second_item)]

            try:
                H1 = float(row_list[6]) / H3
                H2 = float(row_listaway[11]) / H3
                Home_goal = H1 * H2 * H3

                A1 = float(row_list[7]) / A3
                A2 = float(row_listaway[10]) / A3
                Away_goal = A1 * A2 * A3
            except (ValueError, ZeroDivisionError) as e:
                print(
                    f"[{league}] Skipping {first_item} vs {second_item} — bad stats: {e}")
                continue

            twomatch_goals_probability = (
                1 - poisson.cdf(k=2, mu=Home_goal + Away_goal)) * 100
            threematch_goals_probability = (
                1 - poisson.cdf(k=3, mu=Home_goal + Away_goal)) * 100

            score_probs = [[poisson.pmf(i, avg) for i in range(10)] for avg in [
                Home_goal, Away_goal]]
            outcomes = [[i, j] for i in range(10) for j in range(10)]
            probs = [score_probs[0][i] * score_probs[1][j]
                     for i, j in outcomes]
            most_likely_outcome = outcomes[probs.index(max(probs))]
            most_likely_prob_percent = max(probs) * 100
            probable_scorelines = get_top_probable_scorelines(
                Home_goal, Away_goal, n=5)
            match_odds = analyze_fixture(Home_goal, Away_goal, n=5)

            predictions_list.append({
                'Fixture': f"{first_item} {most_likely_outcome[0]} vs {second_item} {most_likely_outcome[1]}",
                'Away_Team': second_item,   # plain string, not a set
                'Home_Team': first_item,    # plain string, not a set
                'Away_team_score': most_likely_outcome[1],
                'Home_team_score': most_likely_outcome[0],
                'Over 2.5 Goals Probability': f"{threematch_goals_probability:.2f}%",
                'Over 1.5 Goals Probability': f"{twomatch_goals_probability:.2f}%",
                'League': league,
                'Top Scorelines': str(probable_scorelines),
                # 'most_likely_probability': round(most_likely_prob_percent, 2),
                'home_win_probability': match_odds['probabilities']['home_win'],
                'away_win_probability': match_odds['probabilities']['away_win'],
                'draw_probability': match_odds['probabilities']['draw']
            })

        return predictions_list

    except Exception as e:
        print(f"[{league}] ERROR: {e}")
        return []  # Always return a list, never HttpResponse


class AllLeaguesPrediction(View):
    leagues = [
        'spain', 'england', 'france', 'germany', 'italy', 'germany2', 'norway',
        'norway2', 'iceland', 'sweden', 'sweden2', 'portugal', 'netherlands',
        'netherlands2', 'russia', 'belgium', 'turkey', 'ukraine',
        'czechrepublic', 'austria', 'switzerland', 'greece', 'scotland', 'croatia',
        'denmark', 'poland', 'spain2', 'england2', 'italy2', 'france2', 'armenia',
        'belarus', 'brazil', 'bulgaria', 'cyprus', 'finland', 'ireland']

    def get(self, request):
        all_predictions = []
        total_created = 0
        errors = []

        # Run all leagues in parallel (10 threads)
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_league = {
                executor.submit(get_league_prediction, request, league): league
                for league in self.leagues
            }

            for future in as_completed(future_to_league):
                league = future_to_league[future]
                try:
                    predictions = future.result()
                except Exception as e:
                    errors.append({'league': league, 'error': str(e)})
                    continue

                if not predictions:
                    errors.append(
                        {'league': league, 'error': 'No predictions returned'})
                    continue

                for prediction in predictions:
                    try:
                        _, created = Fixture.objects.update_or_create(
                            home_team=prediction['Home_Team'],
                            away_team=prediction['Away_Team'],
                            league=prediction['League'],
                            defaults={
                                'fixture_id': str(uuid4())[:16],
                                'home_team_score': prediction['Home_team_score'],
                                'away_team_score': prediction['Away_team_score'],
                                'date': timezone.now(),
                                'predicted_scorelines': prediction['Top Scorelines'],
                                'over_3_goals_probability': float(prediction['Over 2.5 Goals Probability'].strip('%')),
                                'over_2_goals_probability': float(prediction['Over 1.5 Goals Probability'].strip('%')),
                                'home_win_probability': prediction.get('home_win_probability'),
                                'away_win_probability': prediction.get('away_win_probability'),
                                'draw_probability': prediction.get('draw_probability'),
                            }
                        )
                        total_created += 1 if created else 0
                    except Exception as e:
                        errors.append(
                            {'league': league, 'fixture': prediction.get('Fixture'), 'error': str(e)})

                all_predictions.extend(predictions)
                # try:
                #     response = requests.post(
                #         'https://api.usepalmer.com/prediction/add/',
                #         json={'prediction': json.dumps(all_predictions)},
                #         timeout=10
                #     )
                #     response.raise_for_status()

                # except requests.exceptions.RequestException as e:
                #     errors.append({'error': f'Failed to send to prediction API: {str(e)}'})

        return JsonResponse({
            'summary': {
                'total_leagues': len(self.leagues),
                'total_predictions_created': total_created,
                'errors': errors,
            },
            'all_predictions': all_predictions
        }, safe=False)
