import { Component, OnInit, Input, Output, EventEmitter } from '@angular/core';
import { Validators, FormGroup, FormArray, FormBuilder } from '@angular/forms';
import { Contract, Organization, Container } from '../common/models';
import { ClassifierService } from '../common/classifier/classifier.service';
import { ItemsService } from '../common/items.service';
import { SpinnerService } from '../common/spinner/spinner.service';

@Component({
	selector: 'app-page-contracts',
	templateUrl: './page-contracts.component.html',
	styleUrls: ['./page-contracts.component.css']
})
export class PageContractsComponent implements OnInit {

	// инициализирующие данные контракта
	@Input() contract: Contract = new Contract();
	// флаг, если передан - Entity уже определен
	@Input() entityId: number = null;

	public form: FormGroup;
	public container: Container;
	public activeEmitterGroup;
	public formSaveError: boolean = false;

	@Output() onClose = new EventEmitter<boolean>();
	@Output() onContractNew = new EventEmitter<Contract>();
	@Output() onContractUpdate = new EventEmitter<Contract>();

	constructor(
		private _fb: FormBuilder,
		public classifierSvc: ClassifierService,
		private itemsService: ItemsService,
	    public spinner: SpinnerService
	) { }

	ngOnInit() {
		// собираем форму
	    this.form = this._fb.group({
		    valid_from: [''],
		    valid_until: [''],
		    room: [''],
		    rack: [''],
		    shelf: [''],
		    section: [''],
		    folder: [''],
		    entity: [this.entityId || ''],
            emitters: this._fb.array([]),
        });

	    if(this.contract.id){
	    	this.form.patchValue(this.contract);
	    }
    }

    save() {
		// отмечаем поля организаций, как посещенные
	    for(let emitter of (<FormArray>this.form.controls['emitters']).controls){
	    	// отмечаем поле организации
		    (<FormGroup>emitter).controls['address'].markAsDirty();
	    }

	    // валлидируем форму
	    if(!this.form.valid){
	    	this.formSaveError = true;
	    	return false;
	    }

        ///////////////////////////////////
        // Часть кода пропущена в целях соблюдения конфидентиальности
        ///////////////////////////////////

	    // запускаем спиннер
		this.spinner.start();

        // будем слушать заврешение сохранения для закрытия окна
        let promise;
        // в зависимости от режима - либо создаем, либо обновляем данные контракта на сервере
        if(this.contract.id){
			promise = this.itemsService.updateContract(this.contract).then((contract) => {
				this.onContractUpdate.emit(contract);
				return contract;
			});
        }
        else{
			promise = this.itemsService.createContract(this.contract).then((contract) => {
				this.onContractNew.emit(contract);
				return contract;
			});
        }

        // после успешной обработки действия на сервере
        promise.then((contract) => {
		    // обновляем данные контракта
	        Object.assign(this.contract, contract);
	        // закрываем окно
        	this.close();
        }).finally(() => {
        	this.spinner.stop();
        });
        return false;
    }

    close() {
        this.onClose.emit(true);
    }

	// резолвинг адреса
	addressResolve(platform, coord){
		platform.patchValue(coord);
	}

    // при открытии окна организации инициализируем объект
    emitterContainerOpen(data){
		// сначала закроем предыдущее окно
	    if(this.activeEmitterGroup){
	    	this.emitterContainerClose();
	    }
		// только потом откроем новое
	    setTimeout(() => {
			this.container = data.container;
			this.activeEmitterGroup = data.group;
	    }, 0);
	}

    // закрываем окно работы с контейнером
    emitterContainerClose(){
		this.container = null;
		this.activeEmitterGroup = null;
    }
}
