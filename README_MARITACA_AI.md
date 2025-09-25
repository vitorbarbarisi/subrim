# Integração com Maritaca AI

O processor agora suporta o modelo **sabia-3** da [Maritaca AI](https://plataforma.maritaca.ai/modelos) como alternativa ao DeepSeek API.

## Configuração

### 1. Obter API Key da Maritaca AI

1. Acesse [plataforma.maritaca.ai](https://plataforma.maritaca.ai/)
2. Faça login ou crie uma conta
3. Vá para "Chaves de API" e crie uma nova chave
4. Copie a chave gerada

### 2. Configurar Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto com:

```bash
# Maritaca AI Configuration (Priority)
MARITACA_API_KEY=sua_chave_da_maritaca_aqui
MARITACA_MODEL=sabia-3

# DeepSeek API Configuration (Fallback)
DEEPSEEK_API_KEY=sua_chave_do_deepseek_aqui
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 3. Prioridade das APIs

O processor escolhe automaticamente qual API usar:

1. **Maritaca AI** - Se `MARITACA_API_KEY` estiver configurada
2. **DeepSeek API** - Se apenas `DEEPSEEK_API_KEY` estiver configurada
3. **Erro** - Se nenhuma API key estiver configurada

## Vantagens do sabia-3

- **Custo-benefício**: Modelo mais econômico para processamento em grande escala
- **Performance**: Otimizado para tarefas de tradução e extração de pares
- **Qualidade**: Mantém alta qualidade nas traduções chinês-português

## Uso

O processor funciona exatamente igual, mas agora usa a Maritaca AI quando configurada:

```bash
python3 processor.py amor100
```

## Modelos Disponíveis

- `sabia-3` (padrão) - Modelo principal da Maritaca AI
- `sabia-2-small` - Modelo menor para tarefas mais simples
- Outros modelos podem ser configurados via `MARITACA_MODEL`

## API Endpoint

A integração usa o endpoint oficial da Maritaca AI:
- **URL**: `https://chat.maritaca.ai/api/chat/completions`
- **Formato**: Compatível com OpenAI API
- **Autenticação**: Bearer token via `MARITACA_API_KEY`

## Troubleshooting

### Erro de Autenticação
```
Erro de autenticação com Maritaca AI API. Verifique sua API key.
```
- Verifique se a `MARITACA_API_KEY` está correta
- Confirme se a chave está ativa na plataforma Maritaca AI

### Limite de Taxa
```
Limite de taxa da API Maritaca AI excedido. Aguarde alguns minutos.
```
- Aguarde alguns minutos antes de tentar novamente
- Considere implementar delays maiores entre chamadas

### Fallback para DeepSeek
Se a Maritaca AI não estiver disponível, o processor automaticamente usará o DeepSeek API se configurado.
