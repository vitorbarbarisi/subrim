#!/usr/bin/env python3
"""
Script para extrair todos os episódios do Globo Play usando Selenium
Este script simula o scroll infinito para carregar todos os episódios dinamicamente
"""

import time
import json
import csv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GloboPlayScraper:
    def __init__(self, url="https://globoplay.globo.com/v/13385190/?s=0s", headless=False):
        self.url = url
        self.episodes = []
        self.driver = None
        self.headless = headless
        self.json_filename = "globoplay_episodes.json"
        self.csv_filename = "globoplay_episodes.csv"

    def setup_driver(self):
        """Configura o ChromeDriver com opções para simular navegador real"""
        chrome_options = Options()

        # Modo headless (opcional)
        if self.headless:
            chrome_options.add_argument("--headless")

        # Opções básicas
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # User agent mais realista
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        # Opções para evitar detecção de headless
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Simular navegador mais real
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")  # Carrega mais rápido

        try:
            self.driver = webdriver.Chrome(options=chrome_options)

            # Remove webdriver property para evitar detecção
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            logger.info("ChromeDriver inicializado com sucesso (modo stealth)")
        except Exception as e:
            logger.error(f"Erro ao inicializar ChromeDriver: {e}")
            raise

    def wait_for_page_load(self, timeout=30):
        """Espera a página carregar completamente"""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            logger.info("Página carregada completamente")
        except TimeoutException:
            logger.warning("Timeout ao esperar página carregar")

    def scroll_to_bottom(self, scroll_pause_time=3, max_scrolls=100):
        """Simula scroll infinito para carregar todos os episódios com múltiplas estratégias"""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scrolls = 0
        no_change_count = 0
        max_no_change = 5  # Máximo de scrolls sem mudança antes de parar

        # Ajusta comportamento baseado no modo (visual vs headless)
        if not self.headless:
            # Modo visual: mais lento e interativo
            scroll_pause_time = 8  # Mais tempo para o usuário
            max_scrolls = 20  # Menos scrolls automáticos
            logger.info("🔄 MODO VISUAL: Scroll mais lento para permitir interação do usuário")
        else:
            logger.info("🤖 MODO HEADLESS: Scroll automático otimizado")

        logger.info(f"Iniciando scroll - Altura inicial: {last_height}px")

        while scrolls < max_scrolls and no_change_count < max_no_change:
            # Estratégia 1: Scroll gradual (mais natural)
            current_position = self.driver.execute_script("return window.pageYOffset")
            scroll_amount = 800  # Scroll de 800px por vez
            new_position = current_position + scroll_amount

            self.driver.execute_script(f"window.scrollTo(0, {new_position});")
            logger.info(f"Scroll gradual para posição: {new_position}px")

            # Espera conteúdo carregar
            time.sleep(scroll_pause_time)

            # Estratégia 2: Scroll completo para o final (backup)
            if scrolls % 3 == 0:  # A cada 3 scrolls, faz um scroll completo
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)

            # Calcula nova altura da página
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            current_height = self.driver.execute_script("return window.innerHeight + window.pageYOffset")

            # Conta episódios atuais para verificar se novos foram carregados
            try:
                current_episodes = len(self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/v/'][href*='?s=0s']"))
                logger.info(f"Episódios encontrados até agora: {current_episodes}")
            except:
                current_episodes = 0

            logger.info(f"Scroll {scrolls+1}/{max_scrolls} - Altura: {new_height}px - Posição atual: {current_height}px - Episódios: {current_episodes}")

            if new_height == last_height:
                no_change_count += 1
                logger.info(f"Sem mudança na altura ({no_change_count}/{max_no_change})")
            else:
                no_change_count = 0  # Reset counter se houve mudança
                logger.info(f"Altura mudou! Anterior: {last_height}px -> Novo: {new_height}px")

            last_height = new_height
            scrolls += 1

            # Pausa extra se estamos próximos do final
            if current_height >= new_height - 1000:
                logger.info("Próximo do final da página")
                time.sleep(2)

        logger.info(f"Scroll concluído após {scrolls} scrolls. Altura final: {last_height}px")
        return scrolls


    def extract_episodes(self):
        """Extrai informações completas dos episódios da página"""
        try:
            # Verifica se a sessão do navegador ainda está válida
            try:
                self.driver.current_url
            except Exception as e:
                logger.warning("⚠️  Sessão do navegador não está mais disponível")
                logger.warning("💡 Isso pode acontecer se você fechou a janela muito rapidamente")
                logger.info("🔄 Tentando processar dados já coletados...")
                # Se não temos dados, retornamos lista vazia
                if not self.episodes:
                    logger.info("📝 Nenhum dado foi coletado antes do fechamento da janela")
                return

            # Espera os elementos de episódio aparecerem
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[href*='/v/']"))
            )

            # Encontra todos os links de episódios diretamente
            episode_containers = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/v/'][href*='?s=0s']")

            logger.info(f"Encontrados {len(episode_containers)} episódios para processar")

            if episode_containers:
                logger.info("✅ Episódios encontrados com sucesso")
            else:
                logger.warning("⚠️  Nenhum episódio encontrado na página atual")
                logger.info("💡 Dica: Certifique-se de fazer scroll suficiente antes de fechar a janela")

            for i, container in enumerate(episode_containers):
                try:
                    # Extrai informações do container
                    episode_info = self.extract_episode_info(container)

                    logger.debug(f"Container {i+1}: extract_episode_info retornou: {episode_info}")

                    if episode_info:
                        if episode_info not in self.episodes:  # Evita duplicatas
                            self.episodes.append(episode_info)
                            logger.debug(f"✅ Episódio adicionado à lista: {episode_info['episode_number']} - {episode_info['chapter_date']}")
                        else:
                            logger.debug(f"⚠️ Episódio duplicado ignorado: {episode_info['episode_number']}")
                    else:
                        logger.debug(f"❌ extract_episode_info retornou None para container {i+1}")

                except Exception as e:
                    logger.debug(f"Erro ao extrair episódio {i+1}: {e}")
                    continue

            logger.info(f"🎯 Após loop de extração: {len(self.episodes)} episódios na lista")

            # Remove duplicatas baseadas no ID
            logger.info(f"🔄 Iniciando deduplicação: {len(self.episodes)} episódios antes")
            unique_episodes = []
            seen_ids = set()
            for ep in self.episodes:
                if ep['id'] not in seen_ids:
                    unique_episodes.append(ep)
                    seen_ids.add(ep['id'])
                else:
                    logger.debug(f"🗑️ Removendo duplicata: {ep['id']}")

            self.episodes = unique_episodes
            logger.info(f"✅ Após deduplicação: {len(self.episodes)} episódios únicos")

        except Exception as e:
            if "no such window" in str(e).lower():
                logger.warning("⚠️  Janela do navegador foi fechada durante a extração")
                logger.info("💡 Dica: Da próxima vez, aguarde alguns segundos após fazer scroll antes de fechar")
                if self.episodes:
                    logger.info(f"📊 Usando {len(self.episodes)} episódios coletados antes do fechamento")
                else:
                    logger.info("📝 Nenhum episódio foi coletado")
            else:
                logger.error(f"Erro geral na extração: {e}")

    def extract_episode_info(self, container):
        """Extrai informações detalhadas de um container de episódio"""
        try:
            logger.debug("🔍 Iniciando extração de info do container")

            # Extrai URL
            if container.tag_name == 'a':
                href = container.get_attribute("href")
                logger.debug(f"URL direta do link: {href}")
            else:
                link_element = container.find_element(By.CSS_SELECTOR, "a[href*='/v/']")
                href = link_element.get_attribute("href")
                logger.debug(f"URL do elemento encontrado: {href}")

            if not href or '/v/' not in href:
                logger.debug("❌ URL inválida ou não contém '/v/'")
                return None

            # Extrai ID do vídeo
            video_id = href.split('/v/')[1].split('/')[0]
            logger.debug(f"ID do vídeo extraído: {video_id}")

            # Tenta extrair número do episódio e data do capítulo
            episode_number = ""
            chapter_date = ""

            # Tenta extrair diretamente do texto do link
            if hasattr(container, 'text') and container.text:
                full_text = container.text.strip()
                logger.debug(f"Texto completo do container: '{full_text}'")

                # Procura por padrão "Episódio X"
                if "Episódio" in full_text or "Episodio" in full_text:
                    import re
                    match = re.search(r'(?:Episódio|Episodio)\s*(\d+)', full_text, re.IGNORECASE)
                    if match:
                        episode_number = match.group(1)
                        logger.debug(f"Número do episódio encontrado: {episode_number}")

                # Procura por padrão "Capítulo de DD/MM/YYYY"
                if "Capítulo de" in full_text:
                    chapter_date = full_text.split("Capítulo de")[1].split("\n")[0].strip()
                    logger.debug(f"Data do capítulo encontrada: {chapter_date}")

            # Fallback se não conseguiu extrair
            if not episode_number:
                # Tenta usar o ID para inferir o número (lógica baseada na URL)
                if video_id.startswith('133'):
                    # Episódios atuais - pode ser mais complexo
                    episode_number = "Atual"
                else:
                    episode_number = "N/A"
                logger.debug(f"Fallback usado para episódio: {episode_number}")

            if not chapter_date:
                chapter_date = f"Capítulo {video_id}"
                logger.debug(f"Fallback usado para capítulo: {chapter_date}")

            # Cria título completo
            if episode_number != "N/A" and episode_number != "Atual":
                full_title = f"Episódio {episode_number}, {chapter_date}"
            else:
                full_title = chapter_date

            result = {
                'id': video_id,
                'episode_number': episode_number,
                'chapter_date': chapter_date,
                'title': full_title,
                'url': href,
                'type': 'episode'
            }

            logger.debug(f"✅ Extração concluída com sucesso: {result}")
            return result

        except Exception as e:
            logger.debug(f"❌ Erro ao extrair info do container: {e}")
            return None

    def save_to_json(self, filename=None):
        """Salva os episódios em arquivo JSON"""
        if filename is None:
            filename = self.json_filename

        try:
            logger.info(f"💾 Salvando {len(self.episodes)} episódios em {filename}...")

            with open(filename, 'w', encoding='utf-8') as f:
                data = {
                    'metadata': {
                        'source_url': self.url,
                        'extraction_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'total_episodes': len(self.episodes)
                    },
                    'episodes': self.episodes
                }
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"✅ Arquivo JSON salvo: {filename} ({len(self.episodes)} episódios)")

            # Verifica se arquivo foi criado
            import os
            if os.path.exists(filename):
                size = os.path.getsize(filename)
                logger.info(f"📁 Arquivo criado: {size} bytes")
            else:
                logger.error(f"❌ Arquivo não foi criado: {filename}")

        except Exception as e:
            logger.error(f"❌ Erro ao salvar JSON: {e}")
            raise

    def save_to_csv(self, filename=None):
        """Salva os episódios em arquivo CSV com informações completas"""
        if filename is None:
            filename = self.csv_filename

        try:
            logger.info(f"💾 Salvando {len(self.episodes)} episódios em {filename}...")

            if self.episodes:
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    # Define as colunas na ordem desejada
                    fieldnames = ['episode_number', 'chapter_date', 'id', 'title', 'url', 'type']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(self.episodes)

                logger.info(f"✅ Arquivo CSV salvo: {filename} ({len(self.episodes)} episódios)")

                # Verifica se arquivo foi criado
                import os
                if os.path.exists(filename):
                    size = os.path.getsize(filename)
                    logger.info(f"📁 Arquivo criado: {size} bytes")
                else:
                    logger.error(f"❌ Arquivo não foi criado: {filename}")
            else:
                logger.warning("⚠️ Nenhum episódio para salvar no CSV")

        except Exception as e:
            logger.error(f"❌ Erro ao salvar CSV: {e}")
            raise

    def run(self, interaction_time=60):
        """Executa todo o processo de scraping"""
        try:
            logger.info("Iniciando scraping do Globo Play...")

            # Setup do driver
            self.setup_driver()

            # Acessa a página
            logger.info(f"Acessando {self.url}")
            self.driver.get(self.url)

            # Espera página carregar
            self.wait_for_page_load()

            # No modo visual, aguarda interação do usuário por tempo limitado
            if not self.headless:
                print("\n" + "="*60)
                print("🔄 MODO INTERATIVO ATIVADO")
                print("📜 INSTRUÇÕES:")
                print("   1. Use a roda do mouse ou setas para fazer scroll")
                print("   2. Continue fazendo scroll até carregar todos os episódios desejados")
                print("   3. Aguarde - os dados serão extraídos automaticamente")
                print("⏹️  NÃO PRECISA FECHAR A JANELA - ela será fechada automaticamente!")
                print("="*60 + "\n")

                # Timer configurável para interação do usuário
                # interaction_time já é passado como parâmetro do método
                start_time = time.time()

                episodes_collected = 0
                last_check = time.time()

                print(f"⏱️  Você tem {interaction_time} segundos para fazer scroll...")
                print("💡 Dica: Faça scroll na página para carregar mais episódios...")

                try:
                    while time.time() - start_time < interaction_time:
                        # Verifica se a janela ainda está aberta
                        self.driver.current_url  # Isso lança uma exceção se a janela for fechada

                        # A cada 3 segundos, verifica se há novos episódios
                        current_time = time.time()
                        if current_time - last_check >= 3:
                            try:
                                # Conta episódios atuais sem salvar (apenas para feedback)
                                current_episodes = len(self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/v/'][href*='?s=0s']"))
                                if current_episodes != episodes_collected:
                                    episodes_collected = current_episodes
                                    elapsed = int(current_time - start_time)
                                    remaining = interaction_time - elapsed
                                    print(f"📊 Episódios detectados: {episodes_collected} ({remaining}s restantes)")
                                    logger.info(f"Episódios detectados: {episodes_collected}")
                                last_check = current_time
                            except Exception as count_error:
                                logger.debug(f"Erro ao contar episódios: {count_error}")

                        time.sleep(1)  # Verifica a cada segundo

                    # Tempo esgotado - extração automática
                    logger.info("⏰ Tempo de interação esgotado - iniciando extração automática")
                    print(f"🎯 Tempo esgotado! Coletando {episodes_collected} episódios detectados...")

                except Exception as e:
                    # Janela foi fechada antes do tempo acabar
                    logger.info("✅ Janela do navegador fechada pelo usuário (antes do timer)")
                    print(f"🎯 Janela fechada! Coletando {episodes_collected} episódios detectados...")
                    # Continua para extração mesmo sem dados coletados

            # Extrai episódios (seja após scroll automático ou manual)
            logger.info("🔍 Iniciando extração de episódios...")
            self.extract_episodes()
            logger.info(f"📊 Após extração: {len(self.episodes)} episódios encontrados")

            # Salva resultados
            logger.info("💾 Salvando dados...")
            self.save_to_json()
            self.save_to_csv()

            logger.info("Scraping concluído com sucesso!")
            logger.info(f"Total de episódios encontrados: {len(self.episodes)}")

            # Debug final
            print(f"\n🎯 DEBUG FINAL:")
            print(f"   Total de episódios na lista: {len(self.episodes)}")
            if self.episodes:
                print(f"   Primeiro episódio: {self.episodes[0]['title'][:50]}...")
                print(f"   Arquivos que deveriam ser criados: {self.json_filename}, {self.csv_filename}")

            return self.episodes

        except Exception as e:
            logger.error(f"Erro durante execução: {e}")
            return []

        finally:
            if self.driver:
                self.driver.quit()

def main():
    """Função principal"""
    import sys
    import argparse

    # Configura parser de argumentos
    parser = argparse.ArgumentParser(description="Scraper do Globo Play para extrair episódios")
    parser.add_argument("--url", default="https://globoplay.globo.com/v/13385190/?s=0s",
                       help="URL da página do Globo Play (padrão: episódio atual)")
    parser.add_argument("--output", default="globoplay_episodes",
                       help="Nome base para os arquivos de saída (padrão: globoplay_episodes)")
    parser.add_argument("--headless", action="store_true",
                       help="Executar em modo headless (sem interface gráfica)")
    parser.add_argument("--interaction-time", type=int, default=60,
                       help="Tempo em segundos para interação do usuário no modo visual (padrão: 60)")

    args = parser.parse_args()

    # Determina modo de execução
    headless = args.headless
    if headless:
        print("🚀 Executando em modo HEADLESS (sem interface gráfica)")
    else:
        print("🚀 Executando em modo VISUAL (com interface gráfica)")
        print("💡 IMPORTANTE: Faça scroll MANUALMENTE na página para carregar mais episódios!")
        print("   Feche a janela quando terminar de fazer scroll.")

    print(f"📍 URL: {args.url}")
    print(f"📁 Output: {args.output}")

    # Cria scraper com parâmetros
    scraper = GloboPlayScraper(url=args.url, headless=headless)

    # Modifica nomes dos arquivos de saída
    scraper.json_filename = f"{args.output}.json"
    scraper.csv_filename = f"{args.output}.csv"

    episodes = scraper.run(interaction_time=args.interaction_time)

    # Exibe resumo
    print("\n📊 RESUMO DO SCRAPING:")
    print(f"Total de episódios encontrados: {len(episodes)}")
    print("Arquivos gerados:")
    print(f"- {args.output}.json")
    print(f"- {args.output}.csv")

    if episodes:
        print("\n🔗 PRIMEIROS 10 EPISÓDIOS:")
        for i, ep in enumerate(episodes[:10], 1):
            print(f"{i:2d}. {ep['title']} - {ep['url']}")

if __name__ == "__main__":
    main()
