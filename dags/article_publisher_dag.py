"""
Airflow DAG for AI Publisher - Daily Article Generation
Runs 3 times daily: 6 AM, 2 PM, 8 PM UTC
Fetches from RSS, NewsData, NewsAPI → Creates bundle → Generates articles
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.http.operators.http import SimpleHttpOperator
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


# Task 1: Fetch from RSS feeds
fetch_rss = SimpleHttpOperator(
    task_id='fetch_rss',
    http_conn_id='cloud_run_http',
    endpoint='/admin/sources/fetch-rss',
    method='POST',
    data=json.dumps({
        "topic": TOPIC,
        "random_feeds": True,
        "random_feed_count": 3,
        "max_entries": 20,
    }),
    headers={'Content-Type': 'application/json'},
    dag=dag,
)

# Task 2: Fetch from NewsData.io
fetch_newsdata = SimpleHttpOperator(
    task_id='fetch_newsdata',
    http_conn_id='cloud_run_http',
    endpoint='/admin/sources/fetch-newsdata',
    method='POST',
    data=json.dumps({
        "topic": TOPIC,
        "randomize": True,
        "max_sources": 10,
    }),
    headers={'Content-Type': 'application/json'},
    dag=dag,
)

# Task 3: Fetch from NewsAPI.org
fetch_newsapi = SimpleHttpOperator(
    task_id='fetch_newsapi',
    http_conn_id='cloud_run_http',
    endpoint='/admin/sources/fetch-newsapi',
    method='POST',
    data=json.dumps({
        "topic": TOPIC,
        "randomize": True,
        "max_sources": 10,
    }),
    headers={'Content-Type': 'application/json'},
    dag=dag,
)

# Task 4: Create bundle from stored sources
create_bundle = SimpleHttpOperator(
    task_id='create_bundle',
    http_conn_id='cloud_run_http',
    endpoint='/admin/bundles/create',
    method='POST',
    data='''{
        "topic": "''' + TOPIC + '''",
        "mode": "{{ task_instance.xcom_pull(task_ids='select_mode', key='selected_mode') }}",
        "max_sources": 5,
        "min_sources": 3
    }''',
    headers={'Content-Type': 'application/json'},
    dag=dag,
    do_xcom_push=True,
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

# Task 6: Generate article from bundle
generate_article = SimpleHttpOperator(
    task_id='generate_article',
    http_conn_id='cloud_run_http',
    endpoint='/admin/generate',
    method='POST',
    data='''{"bundle_id": "{{ task_instance.xcom_pull(task_ids='extract_bundle_id', key='bundle_id') }}"}''',
    headers={'Content-Type': 'application/json'},
    dag=dag,
)

# Task 7: Verify article in Firestore (optional - just logs)
verify_storage = SimpleHttpOperator(
    task_id='verify_storage',
    http_conn_id='cloud_run_http',
    endpoint='/admin/status',
    method='GET',
    dag=dag,
)

# Define task dependencies
[fetch_rss, fetch_newsdata, fetch_newsapi, select_mode] >> create_bundle
create_bundle >> extract_id >> generate_article >> verify_storage
