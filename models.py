from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Narrative(db.Model):
    __tablename__ = "narratives"

    id = db.Column(db.Integer, primary_key=True)
    fetch_date = db.Column(db.Date, unique=True, index=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    articles = db.relationship(
        "Article", backref="narrative", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def today_articles(self):
        return [a for a in self.articles if a.article_type == "today"]

    @property
    def weekly_groups(self):
        """Return list of (week_label, articles) for week_1 … week_4."""
        groups = []
        for i in range(1, 5):
            key = f"week_{i}"
            arts = [a for a in self.articles if a.article_type == key]
            if arts:
                groups.append((arts[0].week_label, arts))
        return groups


class Article(db.Model):
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    narrative_id = db.Column(
        db.Integer, db.ForeignKey("narratives.id"), nullable=False
    )
    title = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(100))
    description = db.Column(db.Text)
    url = db.Column(db.String(1000))
    published_at = db.Column(db.String(20))
    article_type = db.Column(db.String(20), nullable=False)  # 'today' | 'week_1'..'week_4'
    week_label = db.Column(db.String(50))
