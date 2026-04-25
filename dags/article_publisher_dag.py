"""
Airflow DAG for AI Publisher - Daily Article Generation
Runs 3 times daily: 6 AM, 2 PM, 8 PM UTC
Fetches from RSS, NewsData, NewsAPI → Creates bundle → Generates articles
"""

from datetime import datetime, timedelta
from airflow import DAG
import requests
from airflow.models import Variable
from airflow.operators.python import PythonOperator
import json
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuration
CLOUD_RUN_URL = Variable.get("CLOUD_RUN_URL", "https://ai-publisher-975738038281.us-central1.run.app")
TOPIC = "technology"
CONNECT_TIMEOUT_SECONDS = int(Variable.get("HTTP_CONNECT_TIMEOUT_SECONDS", "20"))
READ_TIMEOUT_SECONDS = int(Variable.get("HTTP_READ_TIMEOUT_SECONDS", "300"))

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2026, 4, 12),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'article_publisher',
    default_args=default_args,
    description='AI Publisher - Daily Article Generation (3x daily)',
    schedule_interval='0 6,14,20 * * *',  # 6 AM, 2 PM, 8 PM UTC
    catchup=False,
    tags=['ai-publisher', 'production'],
)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_HTTP = _build_session()


def _request_json(method: str, endpoint: str, payload: dict | None = None) -> str:
    url = f"{CLOUD_RUN_URL}{endpoint}"
    start = time.perf_counter()
    response = _HTTP.request(
        method=method,
        url=url,
        json=payload,
        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
    )
    elapsed = time.perf_counter() - start
    print(f"{endpoint} completed in {elapsed:.2f}s status={response.status_code}")
    response.raise_for_status()
    return response.text


# Helper function to extract bundle_id from response
def extract_bundle_id(**context):
    """Extract bundle_id from create_bundle task response."""
    response = context['task_instance'].xcom_pull(task_ids='create_bundle')
    if isinstance(response, str):
        response = json.loads(response)
    bundle_id = response.get('bundle_id')
    if not bundle_id:
        raise ValueError(f"No bundle_id in response: {response}")
    context['task_instance'].xcom_push(key='bundle_id', value=bundle_id)
    print(f"Bundle ID extracted: {bundle_id}")


def select_mode_for_run(**context):
    """Select article mode based on scheduled run hour (UTC)."""
    logical_date = context.get('logical_date')
    hour = logical_date.hour if logical_date else datetime.utcnow().hour

    # 06:00 -> global_news, 14:00 -> explainer, 20:00 -> az_tech
    hour_to_mode = {
        6: "global_news",
        14: "explainer",
        20: "az_tech",
    }
    mode = hour_to_mode.get(hour, "explainer")

    context['task_instance'].xcom_push(key='selected_mode', value=mode)
    print(f"Selected mode for hour={hour}: {mode}")



def fetch_rss_callable(**context):
    payload = {
        "topic": TOPIC,
        "random_feeds": True,
        "random_feed_count": 3,
        "max_entries": 20,
    }
    return _request_json("POST", "/admin/sources/fetch-rss", payload)

fetch_rss = PythonOperator(
    task_id='fetch_rss',
    python_callable=fetch_rss_callable,
    provide_context=True,
    dag=dag,
)


def fetch_newsdata_callable(**context):
    payload = {
        "topic": TOPIC,
        "randomize": True,
        "max_sources": 10,
    }
    return _request_json("POST", "/admin/sources/fetch-newsdata", payload)

fetch_newsdata = PythonOperator(
    task_id='fetch_newsdata',
    python_callable=fetch_newsdata_callable,
    provide_context=True,
    dag=dag,
)


def fetch_newsapi_callable(**context):
    payload = {
        "topic": TOPIC,
        "randomize": True,
        "max_sources": 10,
    }
    return _request_json("POST", "/admin/sources/fetch-newsapi", payload)

fetch_newsapi = PythonOperator(
    task_id='fetch_newsapi',
    python_callable=fetch_newsapi_callable,
    provide_context=True,
    dag=dag,
)


def create_bundle_callable(**context):
    mode = context['task_instance'].xcom_pull(task_ids='select_mode', key='selected_mode')
    payload = {
        "topic": TOPIC,
        "mode": mode,
        "max_sources": 5,
        "min_sources": 3
    }
    return _request_json("POST", "/admin/bundles/create", payload)

create_bundle = PythonOperator(
    task_id='create_bundle',
    python_callable=create_bundle_callable,
    provide_context=True,
    dag=dag,
)

# Task 4b: Select mode for this run
select_mode = PythonOperator(
    task_id='select_mode',
    python_callable=select_mode_for_run,
    provide_context=True,
    dag=dag,
)

# Task 5: Extract bundle_id from response
extract_id = PythonOperator(
    task_id='extract_bundle_id',
    python_callable=extract_bundle_id,
    provide_context=True,
    dag=dag,
)


def generate_article_callable(**context):
    bundle_id = context['task_instance'].xcom_pull(task_ids='extract_bundle_id', key='bundle_id')
    payload = {"bundle_id": bundle_id}
    response_text = _request_json("POST", "/admin/generate", payload)
    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError:
        response_json = {}
    article_id = response_json.get("article_id")
    if article_id:
        context['task_instance'].xcom_push(key='article_id', value=article_id)
        print(f"Generated article_id: {article_id}")
    return response_text

generate_article = PythonOperator(
    task_id='generate_article',
    python_callable=generate_article_callable,
    provide_context=True,
    dag=dag,
)


def verify_storage_callable(**context):
    return _request_json("GET", "/admin/status")

verify_storage = PythonOperator(
    task_id='verify_storage',
    python_callable=verify_storage_callable,
    provide_context=True,
    dag=dag,
)

# Define task dependencies
[fetch_rss, fetch_newsdata, fetch_newsapi, select_mode] >> create_bundle
create_bundle >> extract_id >> generate_article >> verify_storage
