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


def get_league_prediction(request, league):
    league_data = {}  # Local variable to store league data for this function
    # league = request.data.get('league')
    if not league:
        return HttpResponse({'error': 'League parameter is required.'})

    base_url = 'https://www.soccerstats.com/'
    urlavgtable = f'https://www.soccerstats.com/table.asp?league={league}&tid=d'
    urlfixture = f'https://www.soccerstats.com/latest.asp?league={league}'

    try:
        # Fetch league table data
        response = requests.get(urlavgtable)
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", {"id": "btable"})
        header = table.find_all("th")
        header = [h.text.strip() for h in header]
        rows = table.find_all("tr")[1:]
        league_data[league] = {'header': header, 'rows': []}

        for row in rows[1:]:
            cols = row.find_all('td')
            cols = [col.text.strip() for col in cols]
            league_data[league]['rows'].append(cols)
            print(league_data[league])

        # Send the fixture list and the predictions
        res = requests.get(urlfixture)
        soup = BeautifulSoup(res.content, 'html.parser')
        odd_rowsA = soup.find_all(
            'tr', {'height': '50', 'bgcolor': '#fff5e6'})
        odd_rowsB = soup.find_all(
            'tr', {'height': '42', 'bgcolor': '#fff5e6'})
        cols = []

        if odd_rowsA:
            for row in odd_rowsA:
                teams_td = row.find_all('td')[1]

                # Check for the <br> or <br/> tag
                br_tag = teams_td.find('br')

                # If a <br> tag is found, process the new format
                if br_tag:
                    # Get the text before and after the <br> tag
                    team1 = br_tag.previous_sibling.strip()
                    team2 = br_tag.next_sibling.strip()

                    # Check if both team names were found
                    if team1 and team2:
                        cols.append([team1, team2])
                        print(f'fixtures: {cols}')
                else:
                    # Fallback to the old format (teams in <a> tags)
                    team_links = teams_td.find_all('a')
                    if len(team_links) == 2:
                        team1 = team_links[0].text.strip()
                        team2 = team_links[1].text.strip()
                        cols.append([team1, team2])
                        print(f'fixtures: {cols}')
        elif odd_rowsB:
            for row in odd_rowsB:
                teams_td = row.find_all('td')[1]
                team_links = teams_td.find_all('a')

                # Check if we found two teams (to avoid errors on empty rows)
                if len(team_links) == 2:
                    team1 = team_links[0].text.strip()
                    team2 = team_links[1].text.strip()
                    cols.append([team1, team2])
                    print(f'fixtures: {cols}')
        output = cols

        teams = [row[0] for row in league_data[league]['rows']]
        print(output)

        b_tags = soup.find_all('b')
        table = soup.find(
            "table", style="margin-left:14px;margin-riht:14px;border:1px solid #aaaaaa;border-radius:12px;overflow:hidden;")

        Home_avg = float(100.000)
        if table:
            b_tags = table.find_all("b")
            if len(b_tags) >= 9:
                Home_avg = b_tags[8].text

        Away_avg = float(100.000)
        if table:
            b_tags = table.find_all("b")
            if len(b_tags) >= 11:
                Away_avg = b_tags[10].text

        H3a = Home_avg
        A3a = Away_avg
        H3 = float(H3a)
        A3 = float(A3a)
        predictions_list = []

        for i in output:
            first_item = i[0]
            second_item = i[1]
            print(first_item, second_item)
            if first_item in teams:
                row_list = league_data[league]['rows'][teams.index(
                    first_item)]
                print(first_item)
            if second_item in teams:
                row_listaway = league_data[league]['rows'][teams.index(
                    second_item)]
                print(second_item)

            H1 = ("{:0.2f}".format(float(row_list[6])/H3))
            print(row_list[6])
            H2 = ("{:0.2f}".format(float(row_listaway[11])/H3))
            print(row_listaway[11])
            Home_goal = ("{:0.2f}".format(
                float(H1) * float(H2) * float(H3)))
            A1 = ("{:0.2f}".format(float(row_list[7])/A3))
            print(row_list[7])
            A2 = ("{:0.2f}".format(float(row_listaway[10])/A3))
            print(row_listaway[10])
            Away_goal = ("{:0.2f}".format(
                float(A1) * float(A2) * float(A3)))
            twomatch_goals_probability = ("{:0.2f}".format(
                (1-poisson.cdf(k=2, mu=float(float(Home_goal) + float(Away_goal))))*100))
            threematch_goals_probability = ("{:0.2f}".format(
                (1-poisson.cdf(k=3, mu=float(float(Home_goal) + float(Away_goal))))*100))

            lambda_home = float(Home_goal)
            lambda_away = float(Away_goal)

            score_probs = [[poisson.pmf(i, team_avg) for i in range(
                0, 10)] for team_avg in [lambda_home, lambda_away]]

            outcomes = [[i, j]
                        for i in range(0, 10) for j in range(0, 10)]

            probs = [score_probs[0][i] * score_probs[1][j]
                     for i, j in outcomes]

            most_likely_outcome = outcomes[probs.index(max(probs))]

            most_likely_prob_percent = max(probs) * 100

            probable_scorelines = get_top_probable_scorelines(
                lambda_home, lambda_away, n=5)

            prediction_data = {
                'Fixture': f"{first_item} {most_likely_outcome[0]} vs {second_item} {most_likely_outcome[1]}",
                'Away_Team': {second_item},
                'Home_Team': {first_item},
                'Away_team_score': {most_likely_outcome[1]},
                'Home_team_score': {most_likely_outcome[0]},
                'Over 2.5 Goals Probability': f"{threematch_goals_probability}%",
                'Over 1.5 Goals Probability': f"{twomatch_goals_probability}%",
                'League': f"{league}",
                'Top Scorelines': f"{probable_scorelines}",
            }
            predictions_list.append(prediction_data)
        print(predictions_list)
        return predictions_list
        # return Response(predictions_list, status=status.HTTP_200_OK)

    except Exception as e:
        return HttpResponse({'error': str(e)})


class AllLeaguesPrediction(View):
    leagues = [
        'spain', 'england', 'france', 'germany', 'italy', 'germany2', 'norway',
        'norway2', 'iceland', 'sweden', 'sweden2', 'portugal', 'netherlands',
        'netherlands2', 'russia', 'belgium', 'turkey', 'ukraine',
        'czechrepublic', 'austria', 'switzerland', 'greece', 'scotland', 'croatia',
        'denmark', 'poland', 'spain2', 'england2', 'italy2', 'france2', 'armenia',
        'belarus']

    def get(self, request):
        """
        Run LeaguePrediction for each country and bulk save outcomes to DB after each country
        """
        results = []
        errors = []
        total_created = 0
        outcomes = []

        league_predictor = LeaguePredictionX()
        all_predictions = []

        for league in self.leagues:
            predictions = get_league_prediction(request, league)
            if isinstance(predictions, list):
                for prediction in predictions:
                    # Save to Fixture model
                    Fixture.objects.update_or_create(
                        home_team=list(prediction['Home_Team'])[0],
                        away_team=list(prediction['Away_Team'])[0],
                        league=prediction['League'],
                        fixture_id=str(uuid4())[:16],
                        defaults={
                            'home_team_score': list(prediction['Home_team_score'])[0],
                            'away_team_score': list(prediction['Away_team_score'])[0],
                            'date': timezone.now(),
                            'predicted_scorelines': prediction['Top Scorelines'],
                            'over_3_goals_probability': float(prediction['Over 2.5 Goals Probability'].strip('%')),
                            'over_2_goals_probability': float(prediction['Over 1.5 Goals Probability'].strip('%')),
                        }
                    )
                all_predictions.append(predictions)

        # return JsonResponse(all_predictions, safe=False)
        # Fixture.objects.bulk_create(fixture_objects)
        # total_created = len(fixture_objects)

        return HttpResponse({
            'summary': {
                'total_leagues': len(self.leagues),
                'successful': len(results),
                'failed': len(errors),
                'total_predictions_created': total_created,
                'outcomes': outcomes
            },
            'successful_leagues': results,
            'failed_leagues': errors
        })
