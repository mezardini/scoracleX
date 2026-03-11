import requests
from scipy.stats import poisson
from bs4 import BeautifulSoup


def fetch_data(url):
    try:
        session = requests.Session()
        response = session.get(url)
        soup = BeautifulSoup(response.content, "html.parser")
        return soup
    except Exception as e:
        return None


def calculate_poisson_probs(lambda_home, lambda_away):
    score_probs = [[poisson.pmf(i, team_avg) for i in range(
        0, 10)] for team_avg in [lambda_home, lambda_away]]
    outcomes = [[i, j] for i in range(0, 10) for j in range(0, 10)]
    probs = [score_probs[0][i] * score_probs[1][j] for i, j in outcomes]
    most_likely_outcome = outcomes[probs.index(max(probs))]
    most_likely_prob_percent = max(probs) * 100
    return most_likely_outcome, most_likely_prob_percent


def predict_match_result(home_goals, away_goals):
    if home_goals > away_goals:
        return 'Home', 100 - poisson.cdf(away_goals - 1, home_goals)
    elif home_goals < away_goals:
        return 'Away', 100 - poisson.cdf(home_goals - 1, away_goals)
    else:
        return 'Draw', poisson.pmf(home_goals, home_goals) * 100


def get_top_probable_scorelines(lambda_home, lambda_away, n=3):
    score_probs = [[poisson.pmf(i, team_avg) for i in range(
        0, 10)] for team_avg in [lambda_home, lambda_away]]
    outcomes = [(i, j) for i in range(0, 10) for j in range(0, 10)]
    probs = [score_probs[0][i] * score_probs[1][j] for i, j in outcomes]
    sorted_outcomes = [outcome for _, outcome in sorted(
        zip(probs, outcomes), reverse=True)]
    top_scorelines = sorted_outcomes[:n]
    return top_scorelines
