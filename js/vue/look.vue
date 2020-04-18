<template>
	<div class="look-form look-single" v-if="look">
		<div class="look-single__block_photo-description-buttons">
			<div class="look-single__block_buttons">
				<div class="look__actions">
		            <a class="look__action look__action_save" rel="nofollow" @click="save()" title="Сохранить">
		                <i aria-hidden="true" class="shopicon-floppy"></i>
		            </a>
		            <a class="look__action look__action_save_cancel" rel="nofollow" @click="saveCancel()" title="Отменить">
		                <i aria-hidden="true" class="shopicon-cancel"></i>
		            </a>
		            <a v-if="!look.isCreating" class="look__action look__action_remove" rel="nofollow" @click="remove()" title="Удалить">
		                <i aria-hidden="true" class="shopicon-trash-empty"></i>
		            </a>
					<local-spinner v-show="changing"/>
				</div>
			</div>
			<div class="look-single__block_photo-description">
				<div class="look-form__item">
					<div class="look-form__label">
						Название образа:
					</div>
					<div class="look-form__field">
						<input type="text" v-model="name" placeholder="Название">
					</div>
				</div>
				<div class="look-form__item">
					<div class="look-form__label">
						Основное фото:
					</div>
					<div class="look-form__field">
						<div class="look__photo" ref="el_photo_container">
							<input type="file" accept="image/*" ref="el_file_input" @change="photoUpload($event)">
							<template v-if="photoFile">
								<div class="look__photo_uploading">
									<img-canvas/>
									<div class="look__photo_uploading_croppie" ref="el_photo_croppie"></div>
								</div>
								<div class="look__photo_actions" v-if="croppie">
									<button class="look__photo_action_rotate-left" @click="croppie.rotate(90)">
						                <i aria-hidden="true" class="shopicon-ccw"></i>
						            </button>
									<button class="look__photo_action_rotate-right" @click="croppie.rotate(-90)">
						                <i aria-hidden="true" class="shopicon-cw"></i>
						            </button>
									<button class="look__photo_action_save" @click="photoSave">
						                <i aria-hidden="true" class="shopicon-floppy"></i>
						            </button>
									<button class="look__photo_action_close" @click="photoUploadClose">
						                <i aria-hidden="true" class="shopicon-close"></i>
						            </button>
								</div>
							</template>
							<template v-else>
								<div class="look__photo_view" @click="$refs.el_file_input.click()">
									<template v-if="look.photoMain">
										<div class="look__photo_img">
											<img :src="look.photoMain">
										</div>
									</template>
									<template v-else>
										<div class="look__photo_empty">
											<img-canvas text="Выберите фото-основу"/>
										</div>
									</template>
									<div class="look__photo_dragged-layer">
										<i class="shopicon shopicon-upload"></i>
									</div>
								</div>
							</template>
						</div>
					</div>
				</div>
				<div class="look-form__item">
					<div class="look-form__label">
						Описание:
					</div>
					<div class="look-form__field">
						<textarea class="look__description" v-model="description"></textarea>
					</div>
				</div>
			</div>
		</div>
		<div class="look-form__item look-form__item_products">
			<div class="look-form__label">
				Товары:
			</div>
			<div class="look-form__field">
				<div class="look__products">
					<div @click="productAddMode" class="look__product-add">
						<div class="look__product-add_text">
							Добавить товар
						</div>
						<div class="look__product-add_icon">
							<i class="shopicon shopicon-plus-circled"></i>
						</div>
					</div>
					<component :is="p.component" v-for="p in look.products" :key="p.id"></component>
				</div>
			</div>
		</div>
	</div>
</template>


<script>

import _ from "underscore"
import Croppie from 'croppie'
import 'croppie/croppie.css'
import dragDrop from 'drag-drop'
import {$width, $height} from '../../utils/dom'

export default {
    data(){
        return {
	        croppie: null,
	        photoFile: null,
	        photoDropZone: null,
	        bodyDropZone: null,
	        photoWrapWidth: 0,
	        photoWrapHeight: 0,
        };
    },
	created(){
        // при изменении размера экрана - пересобираем виджет фото
        window.addEventListener('resize', this.photoReadResize);
        // установка обработчика выхода со страницы
		this.$setCheckAvailableCallback(this.checkOut);
	},
	mounted(){
        this.$nextTick(async function () {
	        // загружаем лук на редактирование
			await this.$store.dispatch('look/edit/load', this.$store.state.envLookEdit.lookId);
            // при открытии всегда сбрасываем режим добавления товаров
	        this.$store.dispatch('look/edit/setEditMode', false);

			this.$nextTick(function () {
				// создаем контейнер для перетаскивания файлов
				this.photoDropZone = dragDrop(this.$refs.el_photo_container, {
					onDrop: files => {
					    if(files && files[0]){
				            // загруженный файл
				            this.photoFile = files[0];
				            // выполняем асинхронное чтение файла
				            this.photoRead();
					    }
					}
				});
				// создаем контейнер для перетаскивания файлов
				this.bodyDropZone = dragDrop('html', {
					onDrop: files => {}
				});
			});
        });
	},
	destroyed(){
		window.removeEventListener('resize', this.photoReadResize);
		// разрушаем контейнер перетаскивания
		if(this.photoDropZone){
		    this.photoDropZone();
		}
		if(this.bodyDropZone){
		    this.bodyDropZone();
		}

		// при выходе с экрана редактирования - если не установлен флаг, убираем глобальный редактируемый лук
		if(!this.$store.getters['look/edit/productsModeLook']){
		    this.$store.dispatch('look/edit/unset');
		}
        // установка обработчика выхода со страницы
		this.$unsetCheckAvailableCallback(this.checkOut);
	},
    methods: {
	    // специальная версия, которая будет отслеживать ресайзинг, и перезагружать кропер
	    photoReadResize: _.throttle( function() {
	        this.photoRead();
        }, 500, {leading: false}),
	    // метод инициализации кропера
	    photoRead(){
            if(!this.photoFile){
                return;
            }
            // выполняем асинхронное чтение файла
            let reader = new FileReader();
            reader.onload = (e) => {
                // если ранее был создан объект - разрушаем его
                if(this.croppie){
                    this.croppie.destroy();
                }
                setTimeout(() => {
	                // создаем новый инструмент
	                this.croppie = new Croppie(this.$refs.el_photo_croppie, {
						viewport: {
						    // ширина чуть меньше, что бы визуально выделить область масштабирования
							width: $width('.look__photo_uploading') * 0.85,
							height: $height('.look__photo_uploading') * 0.85,
						},
						enableExif: true,
		                enableOrientation: true
					});

	                this.croppie.bind({
		                url: e.target.result
	                });
                }, 0);
            };
            reader.readAsDataURL(this.photoFile);
	    },
	    photoUpload(event){
            if(event.target.files && event.target.files[0]){
                // загруженный файл
                this.photoFile = event.target.files[0];
	            // выполняем асинхронное чтение файла
	            this.photoRead();
            }
	    },
	    photoUploadClose(){
            // сообщаем о завершении загрузки
		    this.$refs.el_file_input.value = "";
            this.photoFile = null;
            this.croppie.destroy();
            this.croppie = null;
        },
	    async photoSave(){
            // если ранее был создан объект - сохраняем из него
            if(this.croppie){
                // получаем фото
				let blob = await this.croppie.result({
					type: 'blob',
					format: 'jpeg',
					size: {
					    width: this.$store.state.conf.settings.lookPhotoWidth,
						height: this.$store.state.conf.settings.lookPhotoHeight,
					},
				});
				// собираем файл для сохранения из бинарных данных
	            let photo = new File([blob], this.photoFile.name);
				// выполняем сохранение фото
				await this.$store.dispatch('look/edit/photoCreate', photo);
                // сообщаем о завершении загрузки
                this.photoUploadClose();
            }
	    },
	    productAddMode(){
	        // включаем долгий режим жизни образа редактирования
			this.$store.dispatch('look/edit/setEditMode', true);
			// перекидываем на последнюю посещенную страницу или на главную
		    this.$goUrl('/all');
	    },
        async remove(){
            await this.$store.dispatch('look/remove', this.$store.state.envLookEdit.lookId);
            // в случае успешного удаления переходим на страницу списка моих луков
            this.$goUrl(this.$store.state.conf.urls.lookListOwner);
        },
	    async saveCancel(){
		    let lookId = !this.look.isCreating && this.look.idRead;
			await this.$store.dispatch('look/edit/saveCancel');
			if(lookId){
				this.$goUrl(this.$store.state.conf.urls.lookDetail(lookId));
			}
			else{
			    this.$goUrl(this.$store.state.conf.urls.lookListOwner);
			}
	    },
	    async save(){
	        // выполняем сохранение лука
		    let lookId = this.look.idRead;
			await this.$store.dispatch('look/edit/save');
			this.$store.dispatch('look/edit/unset');
			this.$goUrl(this.$store.state.conf.urls.lookDetail(lookId));
	    },
	    async checkOut(){
	        // если при уходе со страницы активен товар для редактирования - предупреждалка не нужна
	        if(this.$store.getters['look/edit/productsModeLook']){
	            return;
	        }
	        return await this.$store.dispatch('look/edit/saveCancel');
		},
    },
	computed: {
		look(){
		    return this.$store.state.look.edit.look;
		},
		changing(){
		    return this.$store.state.look.changing[this.look.id] || this.$store.state.look.edit.changing;
		},
		name: {
			get(){
				return this.look.name;
			},
			set(value){
			    this.$store.dispatch('look/edit/change', {name: value});
			}
		},
		description: {
			get(){
				return this.look.description
			},
			set(value){
			    this.$store.dispatch('look/edit/change', {description: value});
			}
		},
	},
}

</script>

