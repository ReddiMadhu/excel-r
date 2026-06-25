import os
import sys
from dotenv import load_dotenv

# Add the project root to path so imports work
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables
load_dotenv(os.path.join(project_root, ".env"))

from src.server.models.database import Database
from src.rationalization.engine import RationalizationEngine

def main():
    db_path = r'c:\Users\madhu\Desktop\excelrationlization\input files\data\output\bi_governance.db'
    db = Database(db_path)
    engine = RationalizationEngine(db)
    res = engine.run()
    print("Full Pipeline executed successfully:")
    print(res)

if __name__ == '__main__':
    main()
