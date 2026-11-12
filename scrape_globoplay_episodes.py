#!/usr/bin/env python3
"""
Script para extrair todos os episódios do Globo Play usando Selenium
Este script simula o scroll infinito para carregar todos os episódios dinamicamente
"""

import time
import json
import csv
import signal
import sys
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

# Botão na própria página: o usuário rola o quanto quiser e avisa quando acabou.
# Recriado a cada chamada porque a página pode refazer o DOM. Devolve a contagem
# de episódios carregados e se o botão já foi clicado.
CONCLUIR_JS = """
const total = new Set([...document.querySelectorAll("a[href*='/v/'][href*='?s=0s']")]
                      .map(a => a.href)).size;
let b = document.getElementById('subrim-concluir');
if (!b) {
    b = document.createElement('button');
    b.id = 'subrim-concluir';
    b.style.cssText = 'position:fixed;right:24px;bottom:24px;z-index:2147483647;padding:12px 18px;' +
                      'font-size:15px;font-weight:600;color:#fff;background:#1a7f37;border:0;' +
                      'border-radius:8px;cursor:pointer';
    b.onclick = () => { window.__subrimConcluir = true; };
    document.body.appendChild(b);
}
const fim = !!window.__subrimConcluir;
b.textContent = fim ? 'Coletando…' : `✓ Concluir (${total} episódios)`;
return [total, fim];
"""

CONTAR_JS = """
return new Set([...document.querySelectorAll("a[href*='/v/'][href*='?s=0s']")]
               .map(a => a.href)).size;
"""

# Devolve se o botão "Mostrar mais" da página existia (e foi clicado).
MOSTRAR_MAIS_JS = """
const b = [...document.querySelectorAll('button,[role=button],a')]
          .find(e => e.innerText.trim() === 'Mostrar mais');
if (!b) return false;
b.scrollIntoView({block: 'center'});
b.click();
return true;
"""

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


    def click_show_more(self, time_limit, pause=0.5, stall_timeout=15):
        """Clica em "Mostrar mais" até o botão sumir, a lista parar de crescer
        ou ``time_limit`` (segundos) estourar."""
        start_time = time.time()
        total = self.driver.execute_script(CONTAR_JS)
        print(f"📊 Episódios detectados: {total}")

        while self.driver.execute_script(MOSTRAR_MAIS_JS):
            stall_start = time.time()
            while True:
                time.sleep(pause)
                current = self.driver.execute_script(CONTAR_JS)
                if current != total:
                    total = current
                    print(f"📊 Episódios detectados: {total}")
                    break
                if time.time() - stall_start >= stall_timeout:
                    logger.warning(f"⚠️  'Mostrar mais' não carregou novos episódios em {stall_timeout}s: a lista pode estar incompleta")
                    return
            if time.time() - start_time >= time_limit:
                logger.warning(f"⚠️  Limite de {time_limit}s atingido: a lista pode estar incompleta")
                return

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
            episode_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/v/'][href*='?s=0s']")

            logger.info(f"Encontrados {len(episode_links)} episódios para processar")

            if episode_links:
                logger.info("✅ Episódios encontrados com sucesso")
            else:
                logger.warning("⚠️  Nenhum episódio encontrado na página atual")
                logger.info("💡 Dica: Certifique-se de fazer scroll suficiente antes de fechar a janela")

            # Para cada link, encontra o container pai que contém todas as informações
            episode_containers = []
            for link in episode_links:
                container_found = False
                
                # Estratégia 1: Procura por elemento pai direto (li, div, article, etc) que seja um card
                try:
                    direct_parent = link.find_element(By.XPATH, "./..")
                    direct_parent_text = direct_parent.text.strip()
                    # Se o pai direto tem texto razoável (entre 20 e 500 caracteres), provavelmente é o card
                    if 20 < len(direct_parent_text) < 500:
                        episode_containers.append(direct_parent)
                        container_found = True
                except:
                    pass
                
                # Estratégia 2: Se não encontrou, procura por elemento com classes específicas
                if not container_found:
                    try:
                        parent = link.find_element(By.XPATH, "./ancestor::li[1] | ./ancestor::div[contains(@class, 'card') or contains(@class, 'item') or contains(@class, 'episode')][1] | ./ancestor::article[1]")
                        parent_text = parent.text.strip()
                        if 20 < len(parent_text) < 500:
                            episode_containers.append(parent)
                            container_found = True
                    except:
                        pass
                
                # Estratégia 3: Se ainda não encontrou, usa o pai direto mesmo que tenha pouco texto
                if not container_found:
                    try:
                        parent = link.find_element(By.XPATH, "./..")
                        episode_containers.append(parent)
                    except:
                        # Último recurso: usa o próprio link
                        episode_containers.append(link)

            for i, container in enumerate(episode_containers):
                try:
                    # Extrai informações do container (i+1 porque o índice começa em 0)
                    episode_info = self.extract_episode_info(container, episode_index=i+1)

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

    def extract_episode_info(self, container, episode_index=None):
        """Extrai informações detalhadas de um container de episódio"""
        try:
            import re
            logger.debug("🔍 Iniciando extração de info do container")

            # Extrai URL
            if container.tag_name == 'a':
                href = container.get_attribute("href")
                link_element = container
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
            
            # Estratégia 1: Extrai do atributo title do link (mais confiável)
            try:
                title_attr = link_element.get_attribute("title")
                if title_attr:
                    logger.debug(f"Atributo title encontrado: '{title_attr}'")
                    # Procura por padrão "Capítulo de DD/MM/YYYY"
                    date_match = re.search(r'Capítulo de\s+(\d{2}/\d{2}/\d{4})', title_attr, re.IGNORECASE)
                    if date_match:
                        chapter_date = date_match.group(1)
                        logger.debug(f"Data extraída do title: {chapter_date}")
            except:
                pass

            # Tenta encontrar o elemento pai que contém mais informações
            full_text = ""
            parent_element = None
            
            # Estratégia 1: Procura por elemento pai com classes específicas
            try:
                parent_element = link_element.find_element(By.XPATH, "./ancestor::*[contains(@class, 'episode') or contains(@class, 'card') or contains(@class, 'item') or contains(@class, 'chapter') or contains(@class, 'video') or contains(@class, 'content')][1]")
                full_text = parent_element.text.strip()
                logger.debug(f"Texto extraído do elemento pai (estratégia 1): '{full_text[:200]}...'")
            except:
                pass
            
            # Estratégia 2: Se não encontrou, tenta pegar o elemento pai direto (div, article, etc)
            if not full_text:
                try:
                    parent_element = link_element.find_element(By.XPATH, "./..")
                    full_text = parent_element.text.strip()
                    logger.debug(f"Texto extraído do pai direto (estratégia 2): '{full_text[:200]}...'")
                except:
                    pass
            
            # Estratégia 3: Se ainda não encontrou, tenta pegar do container
            if not full_text:
                try:
                    full_text = container.text.strip()
                    logger.debug(f"Texto extraído do container (estratégia 3): '{full_text[:200]}...'")
                except:
                    pass
            
            # Estratégia 4: Último recurso - pega do próprio link
            if not full_text:
                try:
                    full_text = link_element.text.strip()
                    logger.debug(f"Texto extraído do link (estratégia 4): '{full_text[:200]}...'")
                except:
                    full_text = ""
            
            # Se ainda não tem texto, tenta pegar o innerHTML para análise
            if not full_text or len(full_text) < 10:
                try:
                    if parent_element:
                        html_content = parent_element.get_attribute('innerHTML')
                    else:
                        html_content = container.get_attribute('innerHTML')
                    # Extrai texto do HTML removendo tags
                    import re
                    text_from_html = re.sub(r'<[^>]+>', ' ', html_content)
                    text_from_html = ' '.join(text_from_html.split())
                    if text_from_html and len(text_from_html) > len(full_text):
                        full_text = text_from_html
                        logger.debug(f"Texto extraído do HTML (estratégia 5): '{full_text[:200]}...'")
                except:
                    pass

            logger.debug(f"Texto final extraído: '{full_text[:300]}...'")

            # Procura por padrão "X. Capítulo X" ou "Episódio X"
            episode_match = re.search(r'(?:^|\s)(\d+)\.\s*(?:Capítulo|Episódio)', full_text, re.IGNORECASE | re.MULTILINE)
            if episode_match:
                episode_number = episode_match.group(1)
                logger.debug(f"Número do episódio encontrado (padrão X.): {episode_number}")
            else:
                # Tenta padrão "Episódio X"
                episode_match = re.search(r'(?:Episódio|Episodio)\s*(\d+)', full_text, re.IGNORECASE)
                if episode_match:
                    episode_number = episode_match.group(1)
                    logger.debug(f"Número do episódio encontrado (padrão Episódio): {episode_number}")

            # Procura por padrão "Capítulo de DD/MM/YYYY"
            date_match = re.search(r'Capítulo de\s+(\d{2}/\d{2}/\d{4})', full_text, re.IGNORECASE)
            if date_match:
                chapter_date = date_match.group(1)
                logger.debug(f"Data do capítulo encontrada: {chapter_date}")
            else:
                # Tenta padrão alternativo "DD/MM/YYYY"
                date_match = re.search(r'(\d{2}/\d{2}/\d{4})', full_text)
                if date_match:
                    chapter_date = date_match.group(1)
                    logger.debug(f"Data encontrada (padrão alternativo): {chapter_date}")

            # Estratégia 2: Usa JavaScript para encontrar elementos que podem conter o número do episódio
            if not episode_number:
                try:
                    # Procura por elementos h2, h3, h4 no container usando JavaScript
                    headings_text = self.driver.execute_script("""
                        var container = arguments[0];
                        var headings = container.querySelectorAll('h1, h2, h3, h4, h5, h6');
                        var texts = [];
                        for (var i = 0; i < headings.length; i++) {
                            texts.push(headings[i].textContent.trim());
                        }
                        return texts;
                    """, container)
                    
                    for heading_text in headings_text:
                        # Procura por padrão "X. Capítulo X" ou "X. Episódio X"
                        episode_match = re.search(r'^(\d+)\.\s*(?:Capítulo|Episódio)', heading_text, re.IGNORECASE)
                        if episode_match:
                            episode_number = episode_match.group(1)
                            logger.debug(f"Número do episódio encontrado em heading: {episode_number}")
                            break
                except:
                    pass
            
            # Estratégia 3: Procura por número do episódio no texto completo
            if not episode_number and full_text:
                # Procura por padrão "X. Capítulo" no início do texto
                episode_match = re.search(r'^(\d+)\.\s*(?:Capítulo|Episódio)', full_text, re.IGNORECASE | re.MULTILINE)
                if episode_match:
                    episode_number = episode_match.group(1)
                    logger.debug(f"Número do episódio encontrado no texto (padrão X.): {episode_number}")
                else:
                    # Procura por padrão "Capítulo X" ou "Episódio X"
                    episode_match = re.search(r'(?:Capítulo|Episódio)\s+(\d+)', full_text, re.IGNORECASE)
                    if episode_match:
                        episode_number = episode_match.group(1)
                        logger.debug(f"Número do episódio encontrado no texto (padrão Capítulo X): {episode_number}")
            
            # Estratégia 3: Tenta buscar em elementos filhos específicos (h2, h3, etc)
            if not episode_number:
                try:
                    # Procura por elementos h2, h3, h4 que podem conter o título
                    for tag in ['h2', 'h3', 'h4', 'h5']:
                        try:
                            title_elem = container.find_element(By.CSS_SELECTOR, tag)
                            title_text = title_elem.text.strip()
                            
                            episode_match = re.search(r'(?:^|\s)(\d+)\.\s*(?:Capítulo|Episódio)', title_text, re.IGNORECASE)
                            if episode_match:
                                episode_number = episode_match.group(1)
                                logger.debug(f"Número encontrado em {tag}: {episode_number}")
                                break
                        except:
                            continue
                except:
                    pass
            
            # Estratégia 4: Se ainda não encontrou a data, tenta do atributo alt da imagem
            if not chapter_date:
                try:
                    img_elem = container.find_element(By.CSS_SELECTOR, "img")
                    alt_text = img_elem.get_attribute("alt")
                    if alt_text:
                        date_match = re.search(r'Capítulo de\s+(\d{2}/\d{2}/\d{4})', alt_text, re.IGNORECASE)
                        if date_match:
                            chapter_date = date_match.group(1)
                            logger.debug(f"Data encontrada no alt da imagem: {chapter_date}")
                except:
                    pass

            # Fallback se não conseguiu extrair: usa o índice se fornecido
            if not episode_number:
                if episode_index is not None:
                    episode_number = str(episode_index)
                    logger.debug(f"Usando índice como número do episódio: {episode_number}")
                else:
                    episode_number = "N/A"
                    logger.debug(f"Fallback usado para episódio: {episode_number}")

            if not chapter_date:
                chapter_date = f"Capítulo {video_id}"
                logger.debug(f"Fallback usado para capítulo: {chapter_date}")

            # Cria título completo
            if episode_number != "N/A" and episode_number != "Atual":
                if chapter_date and chapter_date != f"Capítulo {video_id}":
                    full_title = f"Episódio {episode_number}, {chapter_date}"
                else:
                    full_title = f"Episódio {episode_number}"
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

            # No modo visual, o usuário rola a página e clica em Concluir
            if not self.headless:
                print("\n" + "="*60)
                print("🔄 MODO INTERATIVO ATIVADO")
                print("📜 INSTRUÇÕES:")
                print("   1. Clique em 'Mostrar mais' na página até carregar todos os episódios")
                print("   2. Clique em '✓ Concluir', no canto inferior direito da página")
                print("⚠️  NÃO feche a janela: os episódios são lidos dela depois do Concluir")
                print(f"⏱️  Limite: {interaction_time} segundos")
                print("="*60 + "\n")

                start_time = time.time()
                episodes_collected = 0

                try:
                    while time.time() - start_time < interaction_time:
                        total, concluido = self.driver.execute_script(CONCLUIR_JS)
                        if total != episodes_collected:
                            episodes_collected = total
                            remaining = int(interaction_time - (time.time() - start_time))
                            print(f"📊 Episódios detectados: {episodes_collected} ({remaining}s restantes)")
                        if concluido:
                            print(f"🎯 Concluído! Coletando {episodes_collected} episódios detectados...")
                            break
                        time.sleep(1)
                    else:
                        print(f"🎯 Tempo esgotado! Coletando {episodes_collected} episódios detectados...")

                except Exception as e:
                    logger.warning(f"⚠️  Janela do navegador fechada antes do Concluir: nada foi coletado ({type(e).__name__})")

            else:
                self.click_show_more(interaction_time)

            # Extrai episódios (carregados pelo headless ou pelo usuário)
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
                       help="Limite em segundos para carregar os episódios, pelo usuário ou pelo headless (padrão: 60)")

    args = parser.parse_args()

    # "Parar" no Manager: sai pelo finally do run(), que fecha o Chrome.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    # Determina modo de execução
    headless = args.headless
    if headless:
        print("🚀 Executando em modo HEADLESS (sem interface gráfica)")
    else:
        print("🚀 Executando em modo VISUAL (com interface gráfica)")
        print("💡 IMPORTANTE: Clique em 'Mostrar mais' na página para carregar mais episódios!")
        print("   Clique em '✓ Concluir' na página quando terminar.")

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
