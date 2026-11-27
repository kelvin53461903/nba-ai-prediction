"""Independent experimental Elo baseline; not Bandwagon proprietary code."""
import math
from collections import defaultdict
from itertools import groupby

class Elo:
    def __init__(self, k=20, home_advantage=65, carry=0.75):
        self.k,self.home_advantage,self.carry=k,home_advantage,carry
        self.ratings=defaultdict(lambda:1500.0)
        self.season=None
    def start_season(self, season):
        if self.season is not None and season != self.season:
            for team in self.ratings:
                self.ratings[team]=1500+self.carry*(self.ratings[team]-1500)
        self.season=season
    def predict(self, home, away, neutral=False):
        d=self.ratings[home]-self.ratings[away]+(0 if neutral else self.home_advantage)
        return 1/(1+10**(-max(-2000,min(2000,d))/400))
    def update(self, home, away, home_points, away_points, probability):
        if home==away or home_points==away_points or min(home_points,away_points)<=0:
            raise ValueError("Invalid final game")
        delta=self.k*(int(home_points>away_points)-probability)
        self.ratings[home]+=delta
        self.ratings[away]-=delta

def backtest(games, test_start):
    """Normalized rows: date (ISO UTC date), season, id, home, away, hp, ap.
    Only completed games. Predict all games on a date before updating ratings.
    Fixed parameters; test_start must be selected before examining test results.
    """
    model=Elo()
    seen=set()
    results=[]
    for day, group in groupby(sorted(games,key=lambda g:g["date"]),key=lambda g:g["date"]):
        batch=list(group)
        if len({g["season"] for g in batch})!=1:
            raise ValueError("Mixed seasons on date")
        model.start_season(batch[0]["season"])
        predictions=[]
        for g in batch:
            if g["id"] in seen or g["home"]==g["away"] or g["hp"]==g["ap"] or min(g["hp"],g["ap"])<=0:
                raise ValueError("Duplicate or invalid game")
            seen.add(g["id"])
            p=model.predict(g["home"],g["away"],g.get("neutral",False))
            predictions.append((g,p))
            if day>=test_start:
                results.append((p,int(g["hp"]>g["ap"])))
        for g,p in predictions:
            model.update(g["home"],g["away"],g["hp"],g["ap"],p)
    if not results: raise ValueError("Empty test set")
    n=len(results)
    return dict(n=n,accuracy=sum((p>=.5)==bool(y) for p,y in results)/n,
                brier=sum((p-y)**2 for p,y in results)/n,
                log_loss=-sum(y*math.log(p)+(1-y)*math.log1p(-p) for p,y in results)/n)

if __name__=="__main__":
    e=Elo()
    assert e.predict("A","B",True)==0.5
    p=e.predict("A","B")
    assert p>0.5
    e.update("A","B",110,100,p)
    assert e.ratings["A"]>1500 and abs(sum(e.ratings.values())-3000)<1e-9
    before=e.ratings["A"]
    e.start_season(2024); e.start_season(2025)
    assert 1500<e.ratings["A"]<before
    rows=[dict(date="2025-01-01",season=2024,id=1,home="A",away="B",hp=110,ap=100),
          dict(date="2025-01-02",season=2024,id=2,home="A",away="B",hp=100,ap=110)]
    assert backtest(rows,"2025-01-02")["n"]==1
    print("PASS: synthetic Elo smoke tests")
