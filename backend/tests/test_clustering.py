from datetime import UTC, datetime, timedelta

from app.linker.clustering import assign_cluster
from app.models import Cluster, Post, Source

NOW = datetime.now(UTC)


def _post(session, external_id, vec, published_at=None):
    source = session.query(Source).first()
    if source is None:
        source = Source(kind="rss", name="R", feed_url="u", category="Economics")
        session.add(source)
        session.flush()
    post = Post(source_id=source.id, external_id=external_id, url="u", title=external_id,
                published_at=published_at or NOW, embedding=vec)
    session.add(post)
    session.commit()
    return post


def test_near_identical_posts_share_a_cluster(session):
    first = _post(session, "a", [1.0] + [0.0] * 1535)
    second = _post(session, "b", [0.99, 0.01] + [0.0] * 1534)

    assert assign_cluster(session, first) == assign_cluster(session, second)
    assert session.query(Cluster).count() == 1


def test_unrelated_posts_get_separate_clusters(session):
    first = _post(session, "a", [1.0] + [0.0] * 1535)
    second = _post(session, "b", [-1.0] + [0.0] * 1535)

    assert assign_cluster(session, first) != assign_cluster(session, second)
    assert session.query(Cluster).count() == 2


def test_posts_outside_the_window_do_not_cluster(session):
    old = _post(session, "a", [1.0] + [0.0] * 1535, published_at=NOW - timedelta(days=3))
    new = _post(session, "b", [1.0] + [0.0] * 1535)

    assert assign_cluster(session, old) != assign_cluster(session, new)
    assert session.query(Cluster).count() == 2


def test_assign_cluster_is_idempotent_for_an_already_clustered_post(session):
    post = _post(session, "a", [1.0] + [0.0] * 1535)

    first_call = assign_cluster(session, post)
    # Move the post far away in embedding space -- if assign_cluster
    # re-evaluated an already-clustered post instead of short-circuiting,
    # this would send it to a new/different cluster on the second call.
    post.embedding = [-1.0] + [0.0] * 1535
    session.commit()

    second_call = assign_cluster(session, post)

    assert first_call == second_call
    assert session.query(Cluster).count() == 1
