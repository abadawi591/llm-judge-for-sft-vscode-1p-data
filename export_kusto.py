from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
import tqdm
import pandas as pd
import os
import json
import click

# Replace these with your values
cluster = "https://gh-analytics.eastus.kusto.windows.net/"
database = "hydro"

# For Azure Active Directory (AAD) authentication using interactive login
kcsb = KustoConnectionStringBuilder.with_interactive_login(cluster)

# Create the Kusto client
client = KustoClient(kcsb)

def execute(query):
    # Run the query
    response = client.execute(database, query)
    # Display the results
    return response.primary_results[0]


def download_data(filename):
    with open(f"{filename}.kql") as f: # You write your query in this file, it will be formatted in python code and sent to the server
        query = f.read()

    # TODO: add your correct columns here!
    columns = ["conversation_id", "turn_index", "source", "message_text"]


       
    try:
        data = execute(query)
        data = [[json.dumps(d) if isinstance(d, dict) or isinstance(d, list) else d for d in row] for row in data]
        
        df = pd.DataFrame(data, columns=columns)
        print(f"Downloaded {len(df)} records")
        
        df.to_json(f"{filename}.jsonl", orient="records", lines=True, index=False)
        print(f"Data saved to {filename}.jsonl")

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        

@click.command()
@click.argument('filename', type=str)
def main(filename):
    """Download data from Kusto using the specified query file.
    
    FILENAME: The name of the .kql file (without extension) to use for the query.
    """
    download_data(filename)


if __name__ == "__main__":
    main()
