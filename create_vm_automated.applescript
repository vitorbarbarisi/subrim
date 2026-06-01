-- Script AppleScript para criar VM Alpine Linux no UTM automaticamente
-- Nota: O UTM não tem API completa de linha de comando, então este script
-- tenta automatizar o máximo possível através da interface

tell application "UTM"
    activate
    delay 2
    
    -- Verificar se UTM está rodando
    if not (application "UTM" is running) then
        display dialog "UTM não está rodando. Por favor, abra o UTM primeiro." buttons {"OK"} default button "OK"
        return
    end if
end tell

-- Informar ao usuário sobre limitações
display dialog "O UTM não permite criação totalmente automatizada de VMs via script." & return & return & "Por favor, siga estas instruções:" & return & return & "1. Clique em 'Create a New Virtual Machine'" & return & "2. Escolha 'Virtualize' → 'Linux'" & return & "3. Selecione 'Use an existing boot ISO image'" & return & "4. Escolha: ~/Downloads/vm_isos/alpine-standard.iso" & return & "5. Configure RAM (2-4GB), CPU (2-4 cores), Disco (20-40GB)" & return & "6. Salve e inicie a VM" buttons {"OK"} default button "OK"

