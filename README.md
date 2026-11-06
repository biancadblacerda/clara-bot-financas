# Clara: assistente de controle de gastos com LLM

A Clara é um bot no Telegram que anota gastos a partir de mensagens escritas do jeito que a gente fala, sem formulário e sem categoria para escolher. Ela usa um LLM para entender a mensagem, guarda o gasto num banco de dados e responde consultas sobre quanto foi gasto no mês.

```
Você:  uber 18,50 ontem
Clara: Anotei! R$ 18,50 em transporte, dia 04/11.
       Errei? Use /desfazer

Você:  almocei no bandejão, 4 reais
Clara: Anotei! R$ 4,00 em alimentação (bandejão), dia 05/11.

Você:  quanto gastei com comida este mês?
Clara: Em novembro de 2026, você gastou R$ 4,00 com alimentação (1 gasto).

Você:  /resumo
Clara: Seus gastos em novembro de 2026:
       • transporte: R$ 18,50
       • alimentação: R$ 4,00
       Total: R$ 22,50
```

## Como funciona

```
Mensagem no Telegram
        │
        ▼
 interpretador.py ── LLM (Gemini) com saída estruturada
        │            → {acao, valor, categoria, descricao, data, mes}
        │            → validação das respostas (categoria, valor, data)
        ▼
     bot.py ──────── registrar → banco.py (SQLite)
        │            consultar → soma por categoria e mês
        │            outro     → mensagem de ajuda
        ▼
 registros.jsonl ─── toda interação é registrada para medir a qualidade
```

1. A mensagem chega pelo Telegram.
2. O LLM classifica a intenção (**registrar**, **consultar** ou **outro**) e extrai os dados. A resposta é obrigada a seguir um esquema JSON definido com Pydantic, então o código nunca precisa interpretar texto livre do modelo.
3. O código valida o que o LLM devolveu antes de usar.
4. O bot executa a ação e responde.

## Decisões de projeto

**Saída estruturada em vez de texto livre.** O LLM não responde ao usuário diretamente: ele só preenche um formulário fixo (ação, valor, categoria, data). Quem escreve a resposta é o código. Isso deixa o comportamento previsível e limita o que uma mensagem maliciosa consegue fazer.

**Não confiar cegamente no LLM.** Mesmo com o formato garantido, o modelo pode errar o conteúdo. Por isso o código corrige categorias inventadas (vira "outros"), recusa registrar gasto sem valor válido e troca datas no futuro ou em formato inválido pela data de hoje.

**Modelo de reserva.** LLMs ficam indisponíveis com frequência (sobrecarga, limite de uso, tempo esgotado). Quando o modelo principal devolve os erros 429, 500, 503 ou 504, o bot tenta automaticamente um segundo modelo. Se nenhum responder em até 20 segundos por tentativa, o usuário recebe um aviso em vez de ficar esperando.

**Modelo configurável.** O nome do modelo fica no arquivo `.env`, não no código. Quando um modelo foi descontinuado durante o desenvolvimento, a correção foi trocar uma linha de configuração.

**Registro de todas as interações.** Cada mensagem, o que o LLM entendeu e eventuais erros ficam no arquivo `registros.jsonl`. Cada uso do `/desfazer` é registrado como um erro de interpretação. É a partir desse registro que vou medir a taxa de acerto do bot com usuários reais e montar um conjunto de teste para comparar versões do prompt.

## Comandos

| Comando | O que faz |
| --- | --- |
| mensagem livre | registra um gasto ou faz uma consulta |
| `/resumo` | gastos do mês atual por categoria |
| `/desfazer` | apaga o último gasto registrado |
| `/start` | instruções de uso |

Categorias: alimentação, mercado, transporte, moradia, contas, saúde, educação, lazer, compras e outros.

## Tecnologias

- **Python 3.12**
- **python-telegram-bot** para a integração com o Telegram
- **Gemini API** (`google-genai`) com saída estruturada
- **Pydantic** para o esquema e a validação das respostas do LLM
- **SQLite** para armazenar os gastos

## Como rodar

1. Crie um bot no Telegram com o [@BotFather](https://t.me/BotFather) e guarde o token.
2. Crie uma chave de API no [Google AI Studio](https://aistudio.google.com).
3. Copie `.env.example` para `.env` e preencha o token, a chave e os nomes dos modelos.
4. Instale as dependências e rode:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Windows
.venv\Scripts\python bot.py
```

No Linux ou Mac, use `.venv/bin/python` no lugar de `.venv\Scripts\python`.

## Estrutura

```
bot.py             # comandos do Telegram, regras de resposta e registro das interações
interpretador.py   # prompt, esquema da resposta, chamada ao LLM e modelo de reserva
banco.py           # criação do banco SQLite, inserção, desfazer e consultas
.env.example       # modelo das configurações (o .env real nunca vai para o GitHub)
```

## Limitações conhecidas

- **Sem memória da conversa.** Cada mensagem é interpretada sozinha, então perguntas de continuação como "e com mercado?" não funcionam.
- **Um gasto por mensagem.** "30 no almoço e 15 no café" registra só um dos dois.
- **Entradas que não são gastos**, como salário recebido ou estorno, ainda podem ser interpretadas como gasto.
- **Roda localmente.** O bot ainda não está hospedado, então só funciona com o computador ligado.

## Próximos passos

- Hospedar o bot e trocar o SQLite por PostgreSQL gerenciado.
- Criar um conjunto de teste com mensagens reais e comparar versões do prompt e modelos diferentes pela taxa de acerto.
- Medir o tempo de resposta e calcular métricas de uso a partir do `registros.jsonl`.
- Pedir confirmação com botões para valores altos e permitir corrigir a categoria.
- Aceitar mensagens de áudio.

## Privacidade

Os gastos ficam guardados no banco de dados do bot, e o texto das mensagens é enviado à API do Gemini para ser interpretado. Antes de abrir para outras pessoas, vou incluir um comando para cada usuário apagar os próprios dados.

## Autora

Bianca Lacerda, estudante de Engenharia de Computação na USP São Carlos.
[LinkedIn](https://www.linkedin.com/in/bianca-lacerda-922355302)
