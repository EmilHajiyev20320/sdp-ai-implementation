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

# Configuration
CLOUD_RUN_URL = Variable.get("CLOUD_RUN_URL", "https://ai-publisher-975738038281.us-central1.run.app")
TOPIC = "technology"

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
    url = f"{CLOUD_RUN_URL}/admin/sources/fetch-rss"
    payload = {
        "topic": TOPIC,
        "random_feeds": True,
        "random_feed_count": 3,
        "max_entries": 20,
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.text

fetch_rss = PythonOperator(
    task_id='fetch_rss',
    python_callable=fetch_rss_callable,
    provide_context=True,
    dag=dag,
)


def fetch_newsdata_callable(**context):
    url = f"{CLOUD_RUN_URL}/admin/sources/fetch-newsdata"
    payload = {
        "topic": TOPIC,
        "randomize": True,
        "max_sources": 10,
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.text

fetch_newsdata = PythonOperator(
    task_id='fetch_newsdata',
    python_callable=fetch_newsdata_callable,
    provide_context=True,
    dag=dag,
)


def fetch_newsapi_callable(**context):
    url = f"{CLOUD_RUN_URL}/admin/sources/fetch-newsapi"
    payload = {
        "topic": TOPIC,
        "randomize": True,
        "max_sources": 10,
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.text

fetch_newsapi = PythonOperator(
    task_id='fetch_newsapi',
    python_callable=fetch_newsapi_callable,
    provide_context=True,
    dag=dag,
)


def create_bundle_callable(**context):
    mode = context['task_instance'].xcom_pull(task_ids='select_mode', key='selected_mode')
    url = f"{CLOUD_RUN_URL}/admin/bundles/create"
    payload = {
        "topic": TOPIC,
        "mode": mode,
        "max_sources": 5,
        "min_sources": 3
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.text

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
    url = f"{CLOUD_RUN_URL}/admin/generate"
    payload = {"bundle_id": bundle_id}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.text

generate_article = PythonOperator(
    task_id='generate_article',
    python_callable=generate_article_callable,
    provide_context=True,
    dag=dag,
)


def verify_storage_callable(**context):
    url = f"{CLOUD_RUN_URL}/admin/status"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.text

verify_storage = PythonOperator(
    task_id='verify_storage',
    python_callable=verify_storage_callable,
    provide_context=True,
    dag=dag,
)

# Define task dependencies
[fetch_rss, fetch_newsdata, fetch_newsapi, select_mode] >> create_bundle
create_bundle >> extract_id >> generate_article >> verify_storage
