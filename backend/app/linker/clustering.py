from datetime import timedelta

from app.models import Cluster, Post


def assign_cluster(session, post: Post, window_hours: int = 24,
                   threshold: float = 0.15) -> int:
    """Attach a post to the cluster of the nearest recent post, or start a new one.

    Idempotent: a post that already carries a cluster_id is returned unchanged
    without re-evaluating its neighbours.
    """
    if post.cluster_id is not None:
        return post.cluster_id

    cluster_id = None
    if post.embedding is not None:
        window_start = post.published_at - timedelta(hours=window_hours)
        window_end = post.published_at + timedelta(hours=window_hours)
        distance = Post.embedding.cosine_distance(post.embedding).label("distance")
        neighbour = (
            session.query(Post, distance)
            .filter(Post.id != post.id)
            .filter(Post.cluster_id.isnot(None))
            .filter(Post.embedding.isnot(None))
            .filter(Post.published_at >= window_start)
            .filter(Post.published_at <= window_end)
            .filter(distance <= threshold)
            .order_by(distance)
            .first()
        )
        if neighbour is not None:
            cluster_id = neighbour[0].cluster_id

    if cluster_id is None:
        cluster = Cluster(representative_post_id=post.id, post_count=0)
        session.add(cluster)
        session.flush()
        cluster_id = cluster.id

    cluster = session.get(Cluster, cluster_id)
    cluster.post_count += 1
    post.cluster_id = cluster_id
    session.commit()
    return cluster_id
