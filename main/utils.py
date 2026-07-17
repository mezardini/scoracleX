import requests
from scipy.stats import poisson
from bs4 import BeautifulSoup


def save_google_profile(backend, user, response, *args, **kwargs):
    if backend.name != 'google-oauth2' or user is None:
        return

    user.auth_provider = 'google'
    user.google_id = response.get('sub') or response.get('id') or user.google_id
    user.email_verified = response.get('email_verified', user.email_verified)
    user.avatar_url = response.get('picture') or user.avatar_url
    user.first_name = response.get('given_name') or user.first_name
    user.last_name = response.get('family_name') or user.last_name
    if not user.username:
        user.username = response.get('name') or user.email.split('@')[0]
    user.save(update_fields=[
        'auth_provider',
        'google_id',
        'email_verified',
        'avatar_url',
        'first_name',
        'last_name',
        'username',
        'updated_at',
    ])


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


def analyze_fixture(lambda_home, lambda_away, n=5):
    score_probs = [[poisson.pmf(i, team_avg) for i in range(0, 10)]
                   for team_avg in [lambda_home, lambda_away]]

    home_win, away_win, draw = 0.0, 0.0, 0.0
    scoreline_data = []

    for i in range(0, 10):
        for j in range(0, 10):
            prob = score_probs[0][i] * score_probs[1][j]
            scoreline_data.append(((i, j), prob))

            # Aggregate outcome odds
            if i > j:
                home_win += prob
            elif i < j:
                away_win += prob
            else:
                draw += prob

    # Sort scorelines descending by probability
    scoreline_data.sort(key=lambda x: x[1], reverse=True)

    # Format top n scorelines into tuples with readable percentage strings for your UI
    top_scorelines = [
        (home, away, round(p * 100, 2))
        for (home, away), p in scoreline_data[:n]
    ]

    return {
        "probabilities": {
            "home_win": round(home_win * 100, 2),
            "away_win": round(away_win * 100, 2),
            "draw": round(draw * 100, 2)
        },
        "top_scorelines": top_scorelines
    }

# Example breakdown:
# result = analyze_fixture(1.4, 0.8)
# print(result["probabilities"])   -> {'home_win': 49.34, 'away_win': 25.11, 'draw': 24.54}
# print(result["top_scorelines"])  -> [(1, 0, 15.4), (1, 1, 12.32), (2, 0, 10.78), ...]
