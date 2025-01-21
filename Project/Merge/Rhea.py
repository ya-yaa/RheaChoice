from typing import List
from fastapi import FastAPI, HTTPException,Request
from fastapi.staticfiles import StaticFiles
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.chat_models import ChatZhipuAI
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.prompts import MessagesPlaceholder, MessagesPlaceholder
from langchain_core.prompts import ChatPromptTemplate
from langserve import add_routes
from dotenv import load_dotenv,find_dotenv
from langgraph.prebuilt import create_react_agent
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import SystemMessage, HumanMessage
from langchain.chains import create_sql_query_chain
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
import re
# 数据库连接配置
db_uri = "mysql+pymysql://root:输入您的sql用户密码@127.0.0.1:3306/输入您的数据库名称"
db = SQLDatabase.from_uri(db_uri)
# 创建智谱AI实例和SQL代理
llm = ChatZhipuAI(model="glm-4",temperature=0.5,api_key="8d11d612c60c8bce5dad8b8600713443.qyeZzF0sqRphExWa")
execute_query = QuerySQLDataBaseTool(db=db)
write_query = create_sql_query_chain(llm,db)
store = {}
def get_session_history(session_id:str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]
system_template=( """                 
    你的名字叫Rhea如果这句话“{question}”是肌肤相关问题，就请按照以下格式输出内容：根据肌肤症状，提供5条护肤建议（每条建议不超过两句话）和5个具体的产品推荐（按照价格由高到低推荐不同价位的产品，先说产品名称和价格（用SQL查询先进行价钱排序来查找不同价位且不同种类的产品，如果在数据库中查到的价格为空，则输出不用说明该产品价格，再说明推荐理由，理由只要一句话）），每次最终输出之前请说“^0^ Rhea知道 ^0^ ”，在推荐产品时先说“[Rhea之选]: ”；如果{question}和肌肤问题无关（只要不是具体的肌肤问题都算无关，比如问产品价格之类的），你就以Rhea的身份和我正常交流就好，不需按照之前给你规定的格式输出，也不用解释为什么没推荐产品！
    数据库里只有一个表，名字叫alldata,表中有5列，分别为index ，name，category，price，effect，你要根据{question}以及之前的{result}生成一个SQL查询并执行，要求SQL查询时去重，不要输出。
    其中数据库的表中category列有以下几个种类：化妆水、原液、精华、祛痘、面霜/乳液、面膜、面霜乳液、面霜/乳液、BB霜气垫；effect列下面主要是各种成分的种类数量，种类包括保湿，抗衰，舒敏，去痘，控油，抗氧化，美白/淡斑，effect列的内容格式大概为“保湿成分：6种 美白/淡斑成分：2种 抗衰成分：6种 抗氧化成分：7种 控油成分：2种 舒敏成分：3种 去痘成分：1种”这种形式，如果我输入的为“黑”，你就要给我推荐美白的相关产品，如果我输入的为“干燥起皮”，你就要给我推荐保湿的相关产品，以此类推。在生成SQL查询时不要用limit来选取产品，而是要通过在effect里面根据成分由多到少进行选取。以下为我的问题、相应的 SQL 查询和 SQL 结果，请回答我的问题。如果你在数据库中没查到相关产品，也不要说你没查到，你还是按照我之前给你规定的格式在网上检索给我进行输出，最后输出内容不能出现和SQL相关的任何字眼
    Question: {question}
    SQL Query: {query}
    SQL Result: {result}
    Answer: 
    """)
prompt_template = ChatPromptTemplate.from_messages([
    ("system",system_template),
    MessagesPlaceholder("chat_history"),
    ("user","{question}")
])
answer_prompt = PromptTemplate.from_template(
    system_template
)
import re  # 引入正则表达式库
def process_query(x):
    query_result = write_query.invoke(x)
    print(f"Generated query result: {query_result}")
    # 定义正则表达式，从查询中提取 SELECT 到第一个分号之前的内容
    select_pattern = r'(SELECT.*?);'
    if isinstance(query_result, str):
        # 搜索 SELECT 到第一个分号之间的内容
        match = re.search(select_pattern, query_result, re.IGNORECASE | re.DOTALL)
        if match:
            sql_query = match.group(1)  # 获取匹配的第一个分组
        else:
            sql_query = ""  # 如果没有匹配，返回空字符串
    else:
        # 对字典中的结果应用同样的搜索过程
        match = re.search(select_pattern, query_result.get("result", ""), re.IGNORECASE | re.DOTALL)
        if match:
            sql_query = match.group(1)
        else:
            sql_query = ""
    # 进一步清理换行符、反引号和多余的空格
    clean_pattern = r'[`\n]+|\s{2,}'
    sql_query = re.sub(clean_pattern, ' ', sql_query).strip()
    print(f"Processed SQL query: {sql_query}")
    return sql_query

def execute_query_result(x):
    print(f"Executing query: {x}")
    return execute_query.run(process_query(x))

chain = (
    RunnablePassthrough.assign(query=process_query).assign(
        result=execute_query_result
    ) | prompt_template
      | llm
      | StrOutputParser())
# chain = prompt_template|llm
with_message_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="question",
    history_messages_key="chat_history",

)

# 执行链
# def process_user_query(user_input: str, chat_history: BaseChatMessageHistory) -> str:
def process_user_query(user_input: str) -> str:
    print("Generating SQL query...")
    query = chain.invoke({"question": user_input})
    # , "chat_history": chat_history.messages
    print(f"Generated SQL query: {query}")

    try:
        # 执行 SQL 查询
        print("Executing SQL query...")
        result = execute_query.run(query.split("\n")[0])
        print(f"Query result: {result}")

        # 生成回答
        response = answer_prompt.invoke({
            # "chat_history": chat_history.messages,
            "question": user_input,
            "query": query,
            "result": result
        })
        return response["result"]
    except Exception as e:
        print(f"Query failed: {str(e)}")
        return f"查询失败: {str(e)}"

_ = load_dotenv(find_dotenv())
# create parser
parser = StrOutputParser()

#  App definition
app = FastAPI(
    title="LangServe Demo",
    description="使用 LangChain 的 Runnable 接口的简单 API 服务器",
    version="0.0.1"
)

#  Adding chain route
add_routes(
    app,
    with_message_history,
    path="/chain",
)

#  Publishing static resources
app.mount("/pages",StaticFiles(directory="./"),name="pages")


#  cors跨域
from fastapi.middleware.cors import CORSMiddleware
# 允许所有来源访问，允许所有方法和标头
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    # allow_headers=["*"],
)

# 数据库查询
@app.post("/query")
async def handle_sql_query(request: Request):
    try:
        data = await request.json()
        user_input = data.get("question")
        session_id = data.get(session_id)
        print(f"Received question: {user_input}")        
        response = process_user_query(user_input)        
        print(f"Response: {response}")
        return {"answer": response}
    except Exception as e:
        print(f"Error handling SQL query: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
"""
python serve.py

每个 LangServe 服务都带有一个简单的内置 UI，用于配置和调用应用程序，并提供流式输出和中间步骤的可见性。
前往 http://localhost:8000/chain/playground/ 试用！
传入与之前相同的输入 - {"language": "chinese", "text": "hi"} - 它应该会像以前一样做出响应。
"""