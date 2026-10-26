import os
os.environ["LAZIOFLOW_LIVE"] = "0"   # i test non chiamano SaluteLazio
os.environ["LAZIOFLOW_AI"] = "0"     # ...né un LLM: deterministici e a costo zero (il test LLM in ai/tests si attiva da solo con la chiave)
