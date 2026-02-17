"""
Fetch recent episode transcripts for analysis.
"""
import sys
import os
import json
import modal

# Modal app for accessing secrets
app = modal.App("fetch-transcripts")

# Use same image as main pipeline
image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install("psycopg2-binary", "requests")
)

@app.function(
    image=image,
    secrets=[modal.Secret.from_name("mwp-secrets")],
    timeout=300
)
def fetch_episodes():
    """Fetch last 3 episodes with transcripts."""
    import psycopg2
    import requests

    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        return {"error": "POSTGRES_URL not set"}

    try:
        conn = psycopg2.connect(postgres_url)
        cur = conn.cursor()

        # Get last 3 episodes
        cur.execute("""
            SELECT episode_number, title, slug, transcript_url, response,
                   show_notes, pub_date::text
            FROM episodes
            ORDER BY episode_number DESC
            LIMIT 3
        """)

        episodes = []
        for row in cur.fetchall():
            episode = {
                "episode_number": row[0],
                "title": row[1],
                "slug": row[2],
                "transcript_url": row[3],
                "ai_response": row[4],  # Full script
                "show_notes": row[5],  # Full show notes
                "pub_date": row[6]
            }

            # If transcript is stored as URL, fetch it
            if row[3] and row[3].startswith('http'):
                try:
                    resp = requests.get(row[3], timeout=10)
                    if resp.status_code == 200:
                        episode["transcript"] = resp.text
                except Exception as e:
                    episode["transcript_error"] = str(e)

            episodes.append(episode)

        cur.close()
        conn.close()

        return {"episodes": episodes}

    except Exception as e:
        return {"error": str(e)}


@app.local_entrypoint()
def main():
    """Main entry point."""
    result = fetch_episodes.remote()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
