import os
import pandas as pd
import sqlite3
import numpy as np
import json
import re
from typing import List, Dict, Tuple
from groq import Groq
import gradio as gr
from sklearn.metrics import accuracy_score
import warnings
warnings.filterwarnings('ignore')

# ------------------------------
# ✅ GROQ API KEY FROM ENVIRONMENT
# ------------------------------
# Don't hardcode API keys - use Hugging Face Secrets
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    print("⚠️ WARNING: GROQ_API_KEY environment variable not set!")
    print("Please add your Groq API key to your Hugging Face Space secrets.")
    print("For demo purposes, the app will continue but API calls will fail.")
    GROQ_API_KEY = "dummy-key-for-demo"

# ------------------------------
# SQL Converter Using Groq API
# ------------------------------

class EnhancedNL2SQLConverter:
    def __init__(self, model_name: str = "llama3-70b-8192"):
        self.model_name = model_name
        self.client = None
        
        try:
            # Initialize Groq client with proper error handling
            if GROQ_API_KEY and GROQ_API_KEY != "dummy-key-for-demo":
                self.client = Groq(api_key=GROQ_API_KEY)
                print(f"✅ Successfully initialized Groq client with model: {self.model_name}")
            else:
                print("⚠️ Groq client not initialized - API key missing")
        except Exception as e:
            print(f"❌ Error initializing Groq client: {str(e)}")
            self.client = None

        self.default_schema = """
        Table: employees
        Columns:
        - id (INTEGER) PRIMARY KEY
        - name (TEXT) NOT NULL
        - department (TEXT)
        - salary (REAL)
        - hire_date (TEXT)
        - manager_id (INTEGER)
        """

    def generate_sql(self, query: str, schema: str = None) -> str:
        try:
            # Check if client is properly initialized
            if not self.client:
                return "ERROR: Groq API client not initialized. Please check your API key."
            
            schema_to_use = schema or self.default_schema

            system_prompt = """You are an expert SQL query generator. Convert natural language questions to SQL queries based on the provided database schema.

Rules:
1. Only return the SQL query, nothing else
2. Use proper SQL syntax
3. Be precise with column names and table names
4. Use appropriate WHERE clauses, JOINs, and aggregations as needed
5. For date comparisons, use proper date format
6. Don't include explanations, just the SQL query"""

            user_prompt = f"""Database Schema:
{schema_to_use}

Natural Language Question: {query}

Generate the SQL query:"""

            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model=self.model_name,
                temperature=0.1,
                max_tokens=200
            )

            sql_query = chat_completion.choices[0].message.content.strip()
            return self._clean_sql(sql_query)

        except Exception as e:
            print(f"Error generating SQL: {str(e)}")
            return f"ERROR: Could not generate SQL query - {str(e)}"

    def _clean_sql(self, sql: str) -> str:
        sql = sql.strip()
        sql = re.sub(r'```sql\n?', '', sql)
        sql = re.sub(r'```\n?', '', sql)
        sql = re.sub(r'^["\']|["\']$', '', sql)
        sql = sql.rstrip(';')

        sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER']
        if not any(sql.upper().startswith(keyword) for keyword in sql_keywords):
            for keyword in sql_keywords:
                if keyword in sql.upper():
                    sql = sql[sql.upper().find(keyword):]
                    break
        return sql

# ------------------------------
# SQL Evaluator & Test Database
# ------------------------------

class SQLEvaluator:
    def __init__(self):
        self.db_path = "test_database.db"
        self.setup_test_database()

    def setup_test_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create employees table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            salary REAL,
            hire_date TEXT,
            manager_id INTEGER
        )''')
        
        # Insert sample data
        sample_data = [
            (1, 'Alice Johnson', 'Engineering', 75000, '2022-01-15', None),
            (2, 'Bob Smith', 'Sales', 65000, '2021-06-20', None),
            (3, 'Charlie Brown', 'Engineering', 80000, '2020-03-10', 1),
            (4, 'Diana Prince', 'HR', 60000, '2023-02-28', None),
            (5, 'Eve Wilson', 'Sales', 70000, '2022-11-05', 2),
            (6, 'Frank Miller', 'Engineering', 85000, '2019-08-12', 1),
            (7, 'Grace Lee', 'Marketing', 55000, '2023-01-20', None),
            (8, 'Henry Davis', 'Engineering', 72000, '2022-07-30', 1)
        ]
        
        cursor.executemany('''
        INSERT OR REPLACE INTO employees (id, name, department, salary, hire_date, manager_id)
        VALUES (?, ?, ?, ?, ?, ?)''', sample_data)
        
        conn.commit()
        conn.close()
        print("✅ Test database initialized successfully")

    def execute_sql(self, sql_query: str) -> Tuple[bool, any]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(sql_query)

            if sql_query.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                conn.close()
                return True, {'columns': columns, 'data': results}
            else:
                conn.commit()
                conn.close()
                return True, "Query executed successfully"
        except Exception as e:
            return False, str(e)

# ------------------------------
# Initialize components with error handling
# ------------------------------
try:
    converter = EnhancedNL2SQLConverter()
    evaluator = SQLEvaluator()
    print("✅ Application components initialized successfully")
except Exception as e:
    print(f"❌ Error initializing components: {str(e)}")
    # Create dummy components for graceful degradation
    converter = None
    evaluator = SQLEvaluator()  # Database component should still work

# ------------------------------
# Gradio Interface Functions
# ------------------------------

def process_nl_query(nl_query: str) -> Tuple[str, str, str]:
    """Process natural language query and return SQL + results"""
    if not nl_query.strip():
        return "", "", "Please enter a natural language query."
    
    try:
        # Check if converter is available
        if not converter:
            return "", "", "❌ Error: SQL converter not initialized. Please check API configuration."
        
        # Generate SQL
        generated_sql = converter.generate_sql(nl_query)
        
        if generated_sql.startswith("ERROR"):
            return generated_sql, "", "❌ Failed to generate SQL query. Please check your API key."
        
        # Execute SQL
        success, result = evaluator.execute_sql(generated_sql)
        
        if success and isinstance(result, dict):
            # Format results as DataFrame
            df = pd.DataFrame(result['data'], columns=result['columns'])
            if len(df) == 0:
                formatted_output = "No results found."
            else:
                formatted_output = df.to_string(index=False)
            return generated_sql, formatted_output, "✅ Query executed successfully!"
        elif success:
            return generated_sql, str(result), "✅ Query executed successfully!"
        else:
            return generated_sql, "", f"❌ Error executing query: {result}"
            
    except Exception as e:
        return "", "", f"❌ Unexpected error: {str(e)}"

def get_sample_queries():
    """Return sample queries for users to try"""
    return [
        "Show all employees in the Engineering department",
        "Find employees with salary greater than 70000",
        "List all employees hired after 2022",
        "Count employees by department",
        "Show the highest paid employee in each department",
        "Find employees who don't have a manager",
        "Show average salary by department"
    ]

def load_sample_query(query):
    """Load a sample query into the input"""
    return query

# ------------------------------
# Gradio UI
# ------------------------------

# Custom CSS for better styling
css = """
.gradio-container {
    max-width: 1200px !important;
}
.sample-queries {
    margin: 10px 0;
}
"""

with gr.Blocks(css=css, title="NL2SQL with Groq AI", theme=gr.themes.Soft()) as iface:
    gr.Markdown("""
    # 🚀 Natural Language to SQL Converter
    
    Convert your natural language questions into SQL queries using **Groq AI** and execute them on a sample employee database!
    
    ### Sample Database Schema:
    **employees** table with columns: `id`, `name`, `department`, `salary`, `hire_date`, `manager_id`
    """)
    
    with gr.Row():
        with gr.Column(scale=2):
            nl_input = gr.Textbox(
                label="💬 Enter Your Question",
                placeholder="e.g., Show all employees in Engineering department",
                lines=2
            )
            
            submit_btn = gr.Button("🔄 Generate & Execute SQL", variant="primary")
            
        with gr.Column(scale=1):
            gr.Markdown("### 📝 Try These Sample Queries:")
            sample_queries = get_sample_queries()
            
            for i, query in enumerate(sample_queries):
                gr.Button(
                    f"{query}", 
                    variant="secondary",
                    size="sm"
                ).click(
                    lambda q=query: q,
                    outputs=nl_input
                )
    
    with gr.Row():
        with gr.Column():
            sql_output = gr.Textbox(
                label="🔧 Generated SQL Query",
                lines=3,
                interactive=False
            )
            
            status_output = gr.Textbox(
                label="📊 Status",
                lines=1,
                interactive=False
            )
            
            results_output = gr.Textbox(
                label="📋 Query Results",
                lines=10,
                interactive=False
            )
    
    # Event handlers
    submit_btn.click(
        fn=process_nl_query,
        inputs=[nl_input],
        outputs=[sql_output, results_output, status_output]
    )
    
    nl_input.submit(
        fn=process_nl_query,
        inputs=[nl_input],
        outputs=[sql_output, results_output, status_output]
    )
    
    gr.Markdown("""
    ### 🔍 About This App:
    - **AI Model**: Groq's Llama3-70B for SQL generation
    - **Database**: SQLite with sample employee data
    - **Features**: Natural language processing, SQL execution, formatted results
    
    ### 💡 Tips:
    - Be specific in your questions
    - Use clear, simple language
    - Try the sample queries to get started
    """)

# Launch the app
if __name__ == "__main__":
    iface.launch()